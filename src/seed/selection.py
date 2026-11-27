"""Resolve the initial table selection and effective row counts."""

from dataclasses import dataclass

from seed.config import ConfigError, SeedConfig, TableConfig
from seed.database import DatabaseError
from seed.inspection import requested_tables
from seed.metadata import DatabaseSchema, TableSchema

MAX_ROWS = 100_000


@dataclass(frozen=True)
class Selection:
    requested: tuple[str, ...]
    tables: dict[str, TableSchema]
    counts: dict[str, int]
    reuse_existing: frozenset[str]


def validate_row_override(filters: list[str], rows: int | None) -> None:
    """Validate an invocation-level row override before connecting."""
    if rows is not None and (len(filters) != 1 or not 0 <= rows <= MAX_ROWS):
        raise ConfigError("--rows requires one --table and a count from 0 to 100000.")


def resolve_selection(
    config: SeedConfig,
    schema: DatabaseSchema,
    filters: list[str],
    rows: int | None = None,
) -> Selection:
    """Resolve the original request and defaults for possible required parents."""
    validate_row_override(filters, rows)
    tables = {table.id.table: table for table in schema.tables}
    initial = (
        requested_tables(schema.target.schema_name, filters) if filters else set(config.tables)
    )
    if not initial:
        initial = {
            name
            for name, table in tables.items()
            if table.kind == "r" and "UNSUPPORTED_RELATION_KIND" not in table.issues
        }
    if initial - tables.keys():
        raise DatabaseError(
            "TABLE_UNAVAILABLE", "A requested table was not found in the selected schema.", 4
        )

    counts: dict[str, int] = {}
    reuse: set[str] = set()
    for name in tables:
        settings = config.tables.get(name, TableConfig())
        counts[name] = config.generation.default_rows if settings.rows is None else settings.rows
        if settings.reuse_existing:
            reuse.add(name)
    if rows is not None:
        (selected,) = initial
        if selected in reuse and rows != 0:
            raise ConfigError("A reused parent requires a zero row count.")
        counts[selected] = rows
    return Selection(tuple(sorted(initial)), tables, counts, frozenset(reuse))
