"""Shared JSON projection of typed generated values."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from seed.metadata import TableId, TableSchema
from seed.streaming import GeneratedRecord, Value

type JsonValue = None | bool | int | str
type JsonRow = tuple[JsonValue, ...]


@dataclass(frozen=True)
class DatasetColumn:
    name: str
    type: str


@dataclass(frozen=True)
class TableSample:
    table: TableId
    columns: tuple[DatasetColumn, ...]
    rows: tuple[JsonRow, ...]

    def payload(self) -> dict[str, object]:
        """Return the version-1 tabular representation."""
        return {**dataset_header(self.table, self.columns), "rows": self.rows}


def dataset_header(table: TableId, columns: tuple[DatasetColumn, ...]) -> dict[str, object]:
    """Describe a table and the ordered positions of its dataset columns."""
    return {
        "table": table.model_dump(by_alias=True),
        "columns": [{"name": column.name, "type": column.type} for column in columns],
    }


def dataset_columns(table: TableSchema) -> tuple[DatasetColumn, ...]:
    """Return writable columns in schema order, with their output type names."""
    return tuple(
        DatasetColumn(
            column.name,
            "timestamptz"
            if column.type.name == "timestamp" and column.type.timezone
            else column.type.name,
        )
        for column in table.columns
        if column.generated is None
    )


def dataset_row(record: GeneratedRecord, columns: tuple[DatasetColumn, ...]) -> JsonRow:
    """Return a positional row in the descriptor order."""
    return tuple(json_value(record.values[column.name], column.type) for column in columns)


def json_value(value: Value, column_type: str) -> JsonValue:
    """Render lossless JSON scalars for the supported PostgreSQL types."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        stamp = value.astimezone(UTC) if value.utcoffset() is not None else value
        return stamp.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if type(value) is int and column_type == "bigint":
        return str(value)
    return value
