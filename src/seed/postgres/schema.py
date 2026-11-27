"""Normalize PostgreSQL reflection into stable, driver-independent metadata."""

from sqlalchemy import URL, Connection, inspect, text
from sqlalchemy.dialects.postgresql import DOMAIN, ENUM
from sqlalchemy.dialects.postgresql.base import PGInspector
from sqlalchemy.engine.interfaces import ReflectedColumn
from sqlalchemy.types import (
    TIMESTAMP,
    UUID,
    VARCHAR,
    BigInteger,
    Boolean,
    Date,
    Float,
    Integer,
    Numeric,
    SmallInteger,
    Text,
)

from seed.metadata import (
    Check,
    ColumnSchema,
    ColumnType,
    DatabaseSchema,
    ForeignKey,
    Inspection,
    Key,
    TableId,
    TableSchema,
    Target,
    UniqueKey,
    digest,
)
from seed.postgres.catalog import enrich_table
from seed.postgres.connection import DatabaseError


def reflect_schema(
    connection: Connection,
    url: URL,
    schema_name: str,
    *,
    require_read_only: bool = True,
) -> Inspection:
    """Reflect a schema from a read-only snapshot or a guarded write transaction."""
    if require_read_only and connection.scalar(text("SHOW transaction_read_only")) != "on":
        raise DatabaseError(
            "SCHEMA_INSPECTION_FAILED", "Inspection requires a read-only session.", 4
        )
    major = int(connection.scalar(text("SHOW server_version_num"))) // 10000
    if major not in range(15, 20):
        raise DatabaseError("UNSUPPORTED_SERVER", "Seed supports PostgreSQL majors 15–19.", 4)
    inspector = inspect(connection)
    if not isinstance(inspector, PGInspector):
        raise DatabaseError("UNSUPPORTED_SERVER", "A PostgreSQL connection is required.", 4)
    schemas = tuple(
        sorted(
            name
            for name in inspector.get_schema_names()
            if name != "information_schema" and not name.startswith("pg_")
        )
    )
    if schema_name not in schemas or not connection.scalar(
        text("SELECT has_schema_privilege(:schema, 'USAGE')"), {"schema": schema_name}
    ):
        raise DatabaseError("SCHEMA_UNAVAILABLE", "The selected schema is unavailable.", 4)

    relations = connection.execute(
        text(
            "SELECT c.relname, c.relkind, c.oid FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relkind IN ('r', 'p', 'v', 'm', 'f')"
        ),
        {"schema": schema_name},
    ).mappings()
    tables, identities, definitions = [], [], []
    for row in sorted(relations, key=lambda item: item["relname"]):
        table = row["relname"]
        identity = TableId(schema=schema_name, table=table)
        record, raw = _reflect_table(inspector, identity, row["relkind"])
        record, supplemental = enrich_table(connection, int(row["oid"]), record)
        tables.append(record)
        identities.append((table, int(row["oid"])))
        definitions.append([raw, supplemental])

    target = Target(
        host=url.host or "",
        port=url.port or 5432,
        database=str(connection.scalar(text("SELECT current_database()"))),
        schema=schema_name,
    )
    fingerprint = digest(
        [schema_name, [item.model_dump(mode="json", by_alias=True) for item in tables]]
    )
    return Inspection(
        DatabaseSchema(
            target=target,
            server_major=major,
            schemas=schemas,
            tables=tuple(tables),
            fingerprint=fingerprint,
        ),
        tuple(identities),
        digest(definitions),
    )


def _reflect_table(
    inspector: PGInspector,
    identifier: TableId,
    kind: str,
) -> tuple[TableSchema, object]:
    name, schema = identifier.table, identifier.schema_name
    reflected = inspector.get_columns(name, schema=schema)
    columns = tuple(_column(item, index) for index, item in enumerate(reflected, start=1))
    if kind not in {"r", "p", "f"}:
        return TableSchema(id=identifier, kind=kind, columns=columns), [
            item.get("default") for item in reflected
        ]
    pk = inspector.get_pk_constraint(name, schema=schema)
    pk_columns = tuple(pk.get("constrained_columns") or ())
    primary = Key(name=pk.get("name") or "", columns=pk_columns) if pk_columns else None
    fks = inspector.get_foreign_keys(name, schema=schema, postgresql_ignore_search_path=True)
    foreign = tuple(
        sorted(
            (
                ForeignKey(
                    name=item.get("name") or "",
                    columns=tuple(item["constrained_columns"]),
                    parent=TableId(
                        schema=item.get("referred_schema") or schema, table=item["referred_table"]
                    ),
                    parent_columns=tuple(item["referred_columns"]),
                    match=item.get("options", {}).get("match", "SIMPLE"),
                    deferrable=item.get("options", {}).get("deferrable", False),
                    on_update=item.get("options", {}).get("onupdate", "NO ACTION"),
                    on_delete=item.get("options", {}).get("ondelete", "NO ACTION"),
                )
                for item in fks
            ),
            key=lambda item: item.name,
        )
    )
    unique = tuple(
        sorted(
            (
                UniqueKey(name=item.get("name") or "", columns=tuple(item["column_names"]))
                for item in inspector.get_unique_constraints(name, schema=schema)
            ),
            key=lambda item: item.name,
        )
    )
    reflected_checks = inspector.get_check_constraints(name, schema=schema)
    checks = tuple(
        sorted(
            (Check(name=item.get("name") or "", columns=()) for item in reflected_checks),
            key=lambda item: item.name,
        )
    )
    raw = [
        [item["name"], item.get("default"), item.get("computed"), item.get("identity")]
        for item in reflected
    ]
    return TableSchema(
        id=identifier,
        kind=kind,
        columns=columns,
        primary_key=primary,
        foreign_keys=foreign,
        unique_keys=unique,
        checks=checks,
    ), [raw, sorted((item.get("name") or "", item.get("sqltext", "")) for item in reflected_checks)]


def _column(value: ReflectedColumn, ordinal: int) -> ColumnSchema:
    kind = value["type"]
    name = kind.__visit_name__.lower()
    if isinstance(kind, ENUM):
        normalized = ColumnType(
            name="enum",
            supported=True,
            enum_labels=tuple(kind.enums),
            type_schema=kind.schema,
            type_name=kind.name,
        )
    elif isinstance(kind, TIMESTAMP):
        normalized = ColumnType(
            name=name,
            supported=True,
            timezone=kind.timezone,
            precision=getattr(kind, "precision", None),
        )
    elif isinstance(kind, Numeric) and not isinstance(kind, Float):
        normalized = ColumnType(
            name=name,
            precision=kind.precision,
            scale=kind.scale,
            supported=kind.scale is None
            or (kind.precision is not None and 0 <= kind.scale <= kind.precision),
        )
    elif isinstance(kind, (Text, VARCHAR)) and name in {"text", "varchar"}:
        normalized = ColumnType(
            name=name,
            supported=True,
            length=kind.length,
            collation=kind.collation,
        )
    elif isinstance(kind, SmallInteger):
        normalized = ColumnType(name="smallint", supported=True)
    elif isinstance(kind, BigInteger):
        normalized = ColumnType(name="bigint", supported=True)
    elif isinstance(kind, (Integer, Boolean, Date, UUID)):
        normalized = ColumnType(name=name, supported=True)
    elif isinstance(kind, DOMAIN):
        normalized = ColumnType(
            name="domain",
            supported=False,
            type_schema=kind.schema,
            type_name=kind.name,
        )
    else:
        normalized = ColumnType(name=name, supported=False)
    identity = value.get("identity")
    generated = value.get("computed")
    return ColumnSchema(
        name=value["name"],
        ordinal=ordinal,
        type=normalized,
        nullable=value["nullable"],
        default_kind="expression" if value.get("default") is not None else "none",
        identity=("always" if identity.get("always") else "by_default") if identity else None,
        generated=("stored" if generated.get("persisted") else "virtual") if generated else None,
    )
