"""Stream supported PostgreSQL INSERT statements with typed synthetic values."""

from collections.abc import Iterable
from typing import TextIO

from psycopg.sql import Identifier

from seed.dataset import json_value
from seed.metadata import ColumnType, TableSchema
from seed.streaming import GeneratedRecord, Value

type SqlRows = tuple[TableSchema, Iterable[GeneratedRecord]]

_TYPES = {
    "bigint": "int8",
    "boolean": "bool",
    "date": "date",
    "decimal": "numeric",
    "integer": "int4",
    "numeric": "numeric",
    "smallint": "int2",
    "text": "text",
    "uuid": "uuid",
    "varchar": "varchar",
}


def _type_name(column: ColumnType) -> str:
    if column.name == "enum" and column.type_schema and column.type_name:
        return Identifier(column.type_schema, column.type_name).as_string()
    if column.name == "timestamp":
        return "pg_catalog.timestamptz" if column.timezone else "pg_catalog.timestamp"
    return "pg_catalog." + _TYPES[column.name]


def _literal(value: Value, column: ColumnType, type_name: str) -> str:
    if value is None:
        return "NULL"
    encoded = json_value(value, column.name)
    if isinstance(encoded, bool):
        text = str(encoded).lower()
    else:
        text = str(encoded)
    # Escape controls so a value cannot introduce a physical psql command line.
    quoted = "".join(
        "''"
        if char == "'"
        else "\\\\"
        if char == "\\"
        else f"\\x{ord(char):02x}"
        if ord(char) < 32 or ord(char) == 127
        else char
        for char in text
    )
    return f"E'{quoted}'::{type_name}"


def write_sql(output: TextIO, tables: Iterable[SqlRows]) -> None:
    """Write one transaction for a matching, empty PostgreSQL schema."""
    output.write(
        "BEGIN;\n"
        "SET LOCAL client_encoding TO 'UTF8';\n"
        "SET LOCAL standard_conforming_strings TO on;\n"
        "SET LOCAL search_path TO pg_catalog;\n"
    )
    for table, rows in tables:
        columns = tuple(column for column in table.columns if column.generated is None)
        for row_index, record in enumerate(rows):
            if row_index == 0:
                relation = Identifier(table.id.schema_name, table.id.table).as_string()
                names = ", ".join(Identifier(column.name).as_string() for column in columns)
                types = tuple(_type_name(column.type) for column in columns)
                override = (
                    " OVERRIDING SYSTEM VALUE"
                    if any(column.identity == "always" for column in columns)
                    else ""
                )
                prefix = f"INSERT INTO {relation} ({names}){override} VALUES ("
            values = ", ".join(
                _literal(record.values[column.name], column.type, type_name)
                for column, type_name in zip(columns, types, strict=True)
            )
            output.write(prefix + values + ");\n")
    output.write("COMMIT;\n")
