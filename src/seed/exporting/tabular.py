"""Stream versioned JSON and PostgreSQL-compatible CSV tabular exports."""

import json
from collections.abc import Iterable
from typing import TextIO

from seed.generation.streaming import GeneratedRecord
from seed.metadata import TableId
from seed.reporting.dataset import DatasetColumn, JsonValue, dataset_header, dataset_row

type TabularRows = tuple[TableId, tuple[DatasetColumn, ...], Iterable[GeneratedRecord]]


def _csv_field(value: JsonValue) -> str:
    if value is None:
        return ""
    text = str(value).lower() if isinstance(value, bool) else str(value)
    return '"' + text.replace('"', '""') + '"'


def write_csv(
    output: TextIO,
    columns: tuple[DatasetColumn, ...],
    rows: Iterable[GeneratedRecord],
) -> None:
    """Write a header and quote every non-null cell, preserving embedded LF and CR."""
    output.write(",".join(_csv_field(column.name) for column in columns) + "\n")
    for record in rows:
        output.write(",".join(_csv_field(value) for value in dataset_row(record, columns)) + "\n")


def write_json(output: TextIO, tables: Iterable[TabularRows]) -> None:
    """Write one JSON document with positional rows and no whole-table buffering."""
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))
    output.write('{"version":1,"tables":[')
    for table_index, (table, columns, rows) in enumerate(tables):
        if table_index:
            output.write(",")
        output.write(encoder.encode(dataset_header(table, columns))[:-1])
        output.write(',"rows":[')
        for row_index, record in enumerate(rows):
            if row_index:
                output.write(",")
            output.write(encoder.encode(dataset_row(record, columns)))
        output.write("]}")
    output.write("]}\n")
