"""Application service for read-only schema inspection."""

import re
import warnings
from pathlib import Path

from sqlalchemy import URL
from sqlalchemy.exc import SAWarning

from seed.config import SeedConfig, load_config, resolve_database_url
from seed.database import DatabaseError, parse_database_url, read_session
from seed.metadata import DatabaseSchema
from seed.schema import reflect_schema

_IDENTIFIER = r'(?:"(?:[^"]|"")*"|[^".]+)'
_TABLE_NAME = re.compile(rf"({_IDENTIFIER})(?:\.({_IDENTIFIER}))?")


def _identifier(token: str) -> str:
    return token[1:-1].replace('""', '"') if token.startswith('"') else token


def requested_tables(schema: str, filters: list[str]) -> set[str]:
    """Parse exact, optionally qualified table filters for a single schema."""
    names: set[str] = set()
    for expression in filters:
        match = _TABLE_NAME.fullmatch(expression)
        if not match or "\x00" in expression:
            raise DatabaseError("INVALID_TABLE_FILTER", "Use a valid table filter.", 4)
        first = _identifier(match[1])
        if match[2] is None:
            name = first
        else:
            if first != schema:
                raise DatabaseError(
                    "SCHEMA_MISMATCH", "A table filter belongs to a different schema.", 4
                )
            name = _identifier(match[2])
        if not name:
            raise DatabaseError("INVALID_TABLE_FILTER", "Use a valid table filter.", 4)
        names.add(name)
    return names


def inspect_database(
    config_path: Path, schema_override: str | None, filters: list[str]
) -> DatabaseSchema:
    """Return inspected metadata with optional display filtering."""
    config = load_config(config_path)
    if schema_override is not None and (not schema_override or "\x00" in schema_override):
        raise DatabaseError("INVALID_SCHEMA", "Use a valid PostgreSQL schema name.", 4)
    schema_name = config.database.schema_name if schema_override is None else schema_override
    names = requested_tables(schema_name, filters)
    report = read_schema(config, schema_name)
    if not names:
        return report
    tables = tuple(table for table in report.tables if table.id.table in names)
    if len(tables) != len(names):
        raise DatabaseError(
            "TABLE_UNAVAILABLE", "A requested table was not found in the selected schema.", 4
        )
    return report.model_copy(update={"tables": tables})


def read_schema(config: SeedConfig, schema_name: str, *, url: URL | None = None) -> DatabaseSchema:
    """Read a complete schema through the shared redaction boundary."""
    if url is None:
        url = parse_database_url(resolve_database_url(config))
    with read_session(url, config.database) as connection, warnings.catch_warnings():
        warnings.simplefilter("ignore", SAWarning)
        try:
            return reflect_schema(connection, url, schema_name).schema
        except (ValueError, LookupError, NotImplementedError):
            raise DatabaseError(
                "SCHEMA_INSPECTION_FAILED", "PostgreSQL metadata could not be normalized.", 4
            ) from None
