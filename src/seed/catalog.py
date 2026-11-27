"""Supplement reflected PostgreSQL metadata and classify supported shapes."""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal

from sqlalchemy import Connection, RowMapping, text

from seed.database import DatabaseError
from seed.metadata import Check, ColumnType, Feature, NumericBound, TableSchema, UniqueKey

_COLUMNS = """
SELECT a.attname, a.attnum, a.attgenerated, col.collname,
       coalesce(col.collisdeterministic, true) AS deterministic,
       pg_catalog.pg_get_expr(d.adbin, d.adrelid) AS expression,
       owned.seqstart, owned.seqincrement, owned.seqmin, owned.seqmax, owned.seqcycle,
       owned.used_by_default
FROM pg_catalog.pg_attribute AS a
LEFT JOIN pg_catalog.pg_collation AS col ON col.oid = a.attcollation
LEFT JOIN pg_catalog.pg_attrdef AS d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
LEFT JOIN LATERAL (
    SELECT seq.seqstart, seq.seqincrement, seq.seqmin, seq.seqmax, seq.seqcycle,
           EXISTS (
               SELECT 1 FROM pg_catalog.pg_depend AS ref
               WHERE ref.classid = 'pg_catalog.pg_attrdef'::regclass AND ref.objid = d.oid
                 AND ref.refclassid = 'pg_catalog.pg_class'::regclass
                 AND ref.refobjid = seq.seqrelid
           ) AS used_by_default
    FROM pg_catalog.pg_depend AS dep
    JOIN pg_catalog.pg_sequence AS seq ON seq.seqrelid = dep.objid
    WHERE dep.classid = 'pg_catalog.pg_class'::regclass
      AND dep.refclassid = 'pg_catalog.pg_class'::regclass
      AND dep.refobjid = a.attrelid AND dep.refobjsubid = a.attnum
      AND dep.deptype IN ('a', 'i')
) AS owned ON true
WHERE a.attrelid = :oid AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
"""

_CONSTRAINTS = """
SELECT c.conname, c.contype, c.conkey, c.conindid, c.convalidated, c.condeferrable,
       coalesce((to_jsonb(c)->>'conenforced')::boolean, true) AS enforced,
       coalesce((to_jsonb(c)->>'conperiod')::boolean, false) AS temporal,
       NOT EXISTS (
           SELECT 1 FROM unnest(c.conkey, c.confkey, c.conpfeqop) AS key(local, parent, eq)
           LEFT JOIN pg_catalog.pg_attribute AS a
             ON a.attrelid = c.conrelid AND a.attnum = key.local
           LEFT JOIN pg_catalog.pg_attribute AS b
             ON b.attrelid = c.confrelid AND b.attnum = key.parent
           LEFT JOIN pg_catalog.pg_operator AS o ON o.oid = key.eq
           WHERE a.attnum IS NULL OR b.attnum IS NULL OR o.oid IS NULL
              OR a.atttypid <> b.atttypid OR a.attcollation <> b.attcollation
              OR b.attgenerated <> '' OR o.oprname <> '='
              OR o.oprnamespace <> 'pg_catalog'::regnamespace
       ) AS ordinary_fk,
       pg_catalog.pg_get_expr(c.conbin, c.conrelid) AS expression,
       pg_catalog.pg_get_constraintdef(c.oid) AS definition
FROM pg_catalog.pg_constraint AS c
WHERE c.conrelid = :oid
ORDER BY c.conname, c.contype, c.oid
"""

_INDEXES = """
SELECT i.indexrelid, ic.relname, am.amname, i.indisunique, i.indisvalid, i.indisready,
       i.indislive, i.indimmediate, i.indnullsnotdistinct, i.indisexclusion,
       i.indpred IS NOT NULL AS partial, i.indexprs IS NOT NULL AS expression,
       ARRAY(
            SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY AS k(num, pos)
            LEFT JOIN pg_catalog.pg_attribute AS a ON a.attrelid = i.indrelid AND a.attnum = k.num
            WHERE k.pos <= i.indnkeyatts ORDER BY k.pos
       ) AS columns,
       ARRAY(
            SELECT c.opcdefault FROM unnest(i.indclass) WITH ORDINALITY AS k(oid, pos)
            LEFT JOIN pg_catalog.pg_opclass AS c ON c.oid = k.oid ORDER BY k.pos
       ) AS defaults,
       ARRAY(
            SELECT coalesce(c.collisdeterministic, true)
            FROM unnest(i.indcollation) WITH ORDINALITY AS k(oid, pos)
            LEFT JOIN pg_catalog.pg_collation AS c ON c.oid = k.oid ORDER BY k.pos
       ) AS deterministic,
       pg_catalog.pg_get_indexdef(i.indexrelid) AS definition
FROM pg_catalog.pg_index AS i
JOIN pg_catalog.pg_class AS ic ON ic.oid = i.indexrelid
JOIN pg_catalog.pg_am AS am ON am.oid = ic.relam
WHERE i.indrelid = :oid AND (i.indisunique OR i.indisexclusion)
ORDER BY ic.relname
"""

_RELATION = """
SELECT relispartition, relrowsecurity, relforcerowsecurity,
       EXISTS (SELECT 1 FROM pg_catalog.pg_inherits WHERE inhrelid = :oid
              OR inhparent = :oid) AS inheritance
FROM pg_catalog.pg_class WHERE oid = :oid
"""

_SERVER_LOGIC = """
SELECT t.tgname AS name, 'trigger' AS kind, t.tgenabled::text AS enabled,
       pg_catalog.pg_get_triggerdef(t.oid) AS definition
FROM pg_catalog.pg_trigger AS t WHERE t.tgrelid = :oid AND NOT t.tgisinternal
UNION ALL
SELECT r.rulename, 'rule', r.ev_enabled::text, pg_catalog.pg_get_ruledef(r.oid)
FROM pg_catalog.pg_rewrite AS r WHERE r.ev_class = :oid AND r.rulename <> '_RETURN'
UNION ALL
SELECT p.polname, 'policy', 'O',
       concat_ws(' ', p.polcmd, p.polpermissive, p.polroles,
                 pg_catalog.pg_get_expr(p.polqual, p.polrelid),
                 pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid))
FROM pg_catalog.pg_policy AS p WHERE p.polrelid = :oid
ORDER BY kind, name
"""

_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_CAST = r"(?:::\s*(?:pg_catalog\.)?(?:smallint|integer|bigint|numeric|decimal))?"
_LITERAL = rf"(?:{_NUMBER}|'(?:{_NUMBER})'{_CAST}){_CAST}"
_OPERATOR = r"<=|>=|=|<|>"


def _rows(connection: Connection, statement: str, oid: int) -> Sequence[RowMapping]:
    return connection.execute(text(statement), {"oid": oid}).mappings().all()


def numeric_bounds(expression: str, column: str) -> tuple[NumericBound, ...]:
    """Accept a conjunction of plain comparisons to exact numeric literals."""
    # Quoted identifiers may themselves contain parentheses or the word AND.
    identifier = rf'(?:"{re.escape(column.replace(chr(34), chr(34) * 2))}"'
    if re.fullmatch(r"[a-z_][a-z_0-9$]*", column):
        identifier += rf"|{re.escape(column)}"
    identifier += ")"
    tokens = re.findall(r'"(?:[^"]|"")*"|[()]|[^()"\s]+', expression)
    flattened = " ".join(part for part in tokens if part not in {"(", ")"})
    flattened = re.sub(r"\s+::", "::", flattened)
    comparison = re.compile(
        rf"(?:(?P<forward>{identifier})\s*(?P<op>{_OPERATOR})\s*(?P<num>{_LITERAL})"
        rf"|(?P<revnum>{_LITERAL})\s*(?P<revop>{_OPERATOR})\s*(?P<reverse>{identifier}))"
        r"(?:\s+(?P<and>AND)\s+|$)"
    )
    result: list[NumericBound] = []
    remaining = flattened
    while remaining:
        match = comparison.match(remaining)
        if not match:
            return ()
        operator = (
            match["op"] or {"<": ">", "<=": ">=", "=": "=", ">": "<", ">=": "<="}[match["revop"]]
        )
        literal = match["num"] or match["revnum"]
        value = Decimal(literal.split("::", 1)[0].strip("' "))
        if not value.is_finite() or (match["and"] and match.end() == len(remaining)):
            return ()
        result.append(NumericBound(column=column, operator=operator, value=str(value)))
        remaining = remaining[match.end() :]
    return tuple(result)


def _catalog_failure() -> DatabaseError:
    return DatabaseError("SCHEMA_INSPECTION_FAILED", "PostgreSQL metadata was incomplete.", 4)


def enrich_table(
    connection: Connection,
    oid: int,
    table: TableSchema,
) -> tuple[TableSchema, object]:
    """Verify and classify reflection with catalog data from the same snapshot."""
    columns = _rows(connection, _COLUMNS, oid)
    constraints = _rows(connection, _CONSTRAINTS, oid)
    indexes = _rows(connection, _INDEXES, oid)
    logic = _rows(connection, _SERVER_LOGIC, oid)
    relation_rows = _rows(connection, _RELATION, oid)
    if len(relation_rows) != 1 or [row["attname"] for row in columns] != [
        column.name for column in table.columns
    ]:
        raise _catalog_failure()
    relation = relation_rows[0]
    features: list[Feature] = []
    issues: list[str] = []

    def detected(name: str, reason: str) -> None:
        features.append(Feature(name=name, status="Detected only", reason=reason))
        issues.append(reason)

    if table.kind != "r" or relation["relispartition"] or relation["inheritance"]:
        detected("relation", "UNSUPPORTED_RELATION_KIND")
    else:
        features.append(Feature(name="relation", status="MVP"))
    if relation["relrowsecurity"] or relation["relforcerowsecurity"]:
        detected("row level security", "ROW_LEVEL_SECURITY")
    for logic_item in logic:
        if logic_item["kind"] in {"trigger", "rule"} and logic_item["enabled"] != "D":
            detected(f"{logic_item['kind']} {logic_item['name']}", "ENABLED_SERVER_LOGIC")

    attnames = {row["attnum"]: row["attname"] for row in columns}
    normalized = []
    for model, row in zip(table.columns, columns, strict=True):
        expression = row["expression"] or ""
        if row["used_by_default"] and re.fullmatch(
            r"nextval\('(?:[^']|'')+'::regclass\)", expression
        ):
            default_kind = "owned_serial"
        elif model.identity:
            default_kind = "identity"
        elif re.fullmatch(
            rf"{_LITERAL}|true|false|NULL|'(?:[^']|'')*'(?:::[a-z ]+)?",
            expression,
            re.IGNORECASE,
        ):
            default_kind = "literal"
        else:
            default_kind = "expression" if expression else "none"
        generated = {"s": "stored", "v": "virtual"}.get(row["attgenerated"])
        normalized.append(
            model.model_copy(
                update={
                    "ordinal": row["attnum"],
                    "default_kind": default_kind,
                    "generated": generated,
                    "type": model.type.model_copy(update={"collation": row["collname"]}),
                }
            )
        )
        if not model.type.supported and not generated:
            detected(f"column {model.name}", "UNSUPPORTED_COLUMN_TYPE")
        if default_kind in {"owned_serial", "identity"}:
            offline = (
                row["seqincrement"] == 1
                and not row["seqcycle"]
                and (row["seqmin"] is not None and row["seqmin"] <= 1 <= row["seqmax"])
            )
            features.append(
                Feature(
                    name=f"sequence {model.name}",
                    status="Partial",
                    reason="SERVER_ALLOCATED_KEY" if offline else "UNSUPPORTED_OFFLINE_SEQUENCE",
                )
            )

    column_types = {column.name: column.type for column in normalized}
    indexed = {row["indexrelid"]: row for row in indexes}
    backed = {row["conindid"] for row in constraints if row["contype"] in {"u", "p", "x"}}
    by_name = {(row["contype"], row["conname"]): row for row in constraints}
    checks: list[Check] = []
    unique: list[UniqueKey] = []
    foreign = []
    if table.primary_key is not None:
        key = by_name.get(("p", table.primary_key.name))
        index = indexed.get(key["conindid"]) if key is not None else None
        if (
            index is None
            or not _ordinary_index(index, column_types)
            or (key is not None and key["condeferrable"])
        ):
            detected(f"primary key {table.primary_key.name}", "UNSUPPORTED_PRIMARY_KEY")

    for unique_key in table.unique_keys:
        constraint = by_name.get(("u", unique_key.name))
        index = indexed.get(constraint["conindid"]) if constraint is not None else None
        if constraint is None or index is None:
            raise _catalog_failure()
        supported = _ordinary_index(index, column_types) and not (
            constraint["condeferrable"] or constraint["temporal"]
        )
        unique.append(
            unique_key.model_copy(
                update={
                    "supported": supported,
                    "nulls_distinct": not index["indnullsnotdistinct"],
                }
            )
        )
        if not supported:
            detected(f"unique constraint {unique_key.name}", "UNSUPPORTED_UNIQUE_KEY")

    for item in indexes:
        if item["indisexclusion"]:
            detected(f"index {item['relname']}", "UNSUPPORTED_EXCLUSION")
        elif item["indexrelid"] not in backed:
            supported = _ordinary_index(item, column_types)
            unique.append(
                UniqueKey(
                    name=item["relname"],
                    columns=tuple(c for c in item["columns"] if c is not None),
                    nulls_distinct=not item["indnullsnotdistinct"],
                    source="index",
                    supported=supported,
                )
            )
            if not supported:
                detected(f"index {item['relname']}", "UNSUPPORTED_UNIQUE_KEY")

    constrained: set[str] = set(table.primary_key.columns if table.primary_key else ())
    constrained.update(column for item in unique for column in item.columns)
    used_foreign: set[str] = set()
    for foreign_key in table.foreign_keys:
        fk_catalog = by_name.get(("f", foreign_key.name))
        if fk_catalog is None:
            raise _catalog_failure()
        valid = fk_catalog["convalidated"]
        enforced = fk_catalog["enforced"]
        if (
            not valid
            or not enforced
            or fk_catalog["condeferrable"]
            or fk_catalog["temporal"]
            or not fk_catalog["ordinary_fk"]
            or foreign_key.match != "SIMPLE"
            or foreign_key.parent.schema_name != table.id.schema_name
            or foreign_key.parent == table.id
            or used_foreign.intersection(foreign_key.columns)
            or any(not column_types[column].supported for column in foreign_key.columns)
        ):
            detected(f"foreign key {foreign_key.name}", "UNSUPPORTED_FOREIGN_KEY")
        used_foreign.update(foreign_key.columns)
        foreign.append(
            foreign_key.model_copy(
                update={
                    "validated": valid,
                    "enforced": enforced,
                    "deferrable": fk_catalog["condeferrable"],
                }
            )
        )
    constrained.update(used_foreign)

    numeric = {
        column.name
        for column in normalized
        if column.type.supported
        and column.type.name in {"numeric", "smallint", "integer", "bigint"}
        and column.generated is None
        and column.default_kind not in {"identity", "owned_serial"}
    }
    for row in constraints:
        if row["contype"] != "c":
            continue
        names = tuple(attnames[number] for number in (row["conkey"] or []) if number in attnames)
        bounds: tuple[NumericBound, ...] = ()
        if len(names) == 1 and names[0] in numeric and row["convalidated"] and row["enforced"]:
            bounds = numeric_bounds(row["expression"] or "", names[0])
        if not bounds:
            detected(f"check {row['conname']}", "UNSUPPORTED_CHECK")
        constrained.update(names)
        checks.append(
            Check(
                name=row["conname"],
                columns=names,
                validated=row["convalidated"],
                status="Partial" if bounds else "Detected only",
                bounds=bounds,
            )
        )
    for column in normalized:
        if column.generated == "virtual" or (column.generated and column.name in constrained):
            detected(f"generated column {column.name}", "UNSUPPORTED_GENERATED_COLUMN")

    updated = table.model_copy(
        update={
            "columns": tuple(normalized),
            "foreign_keys": tuple(foreign),
            "unique_keys": tuple(sorted(unique, key=lambda key: (key.name, key.source))),
            "checks": tuple(checks),
            "features": tuple(
                sorted(features, key=lambda feature: (feature.name, feature.reason or ""))
            ),
            "issues": tuple(sorted(set(issues))),
        }
    )
    return updated, [
        [dict(row) for row in group]
        for group in (columns, constraints, indexes, logic, relation_rows)
    ]


def _ordinary_index(index: RowMapping, column_types: Mapping[str, ColumnType]) -> bool:
    return bool(
        index["amname"] == "btree"
        and index["indisvalid"]
        and index["indisready"]
        and index["indislive"]
        and index["indimmediate"]
        and not (index["partial"] or index["expression"] or index["indisexclusion"])
        and index["columns"]
        and all(name in column_types and column_types[name].supported for name in index["columns"])
        and all(index["defaults"])
        and all(index["deterministic"])
    )
