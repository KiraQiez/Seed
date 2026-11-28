"""Human-readable summaries for the terminal."""

import json
from collections.abc import Iterable

from rich import box
from rich.console import Group
from rich.table import Table
from rich.text import Text

from seed.metadata import DatabaseSchema, TableId
from seed.planning.plan import GenerationPlan
from seed.reporting.dataset import JsonValue, TableSample
from seed.reporting.inspection import safe_text
from seed.workflows.apply import ApplyReport
from seed.workflows.export import ExportResult
from seed.workflows.validate import ValidationReport


def _label(table: TableId) -> str:
    return safe_text(f"{table.schema_name}.{table.table}")


def _grid(*columns: str) -> Table:
    table = Table(box=box.SIMPLE, pad_edge=False, header_style="bold cyan")
    for name in columns:
        table.add_column(Text(name))
    return table


def inspection_summary(schema: DatabaseSchema) -> Group:
    tables = _grid("Table", "Columns", "Primary key", "Foreign keys", "Support")
    for table in schema.tables:
        primary = safe_text(", ".join(table.primary_key.columns)) if table.primary_key else "-"
        tables.add_row(
            Text(_label(table.id)),
            str(len(table.columns)),
            Text(primary),
            str(len(table.foreign_keys)),
            "Detected only" if table.issues else "See details",
        )
    target = Text(
        f"PostgreSQL {schema.server_major} · {safe_text(schema.target.database)}"
        f" · schema {safe_text(schema.target.schema_name)}",
        style="bold",
    )
    return Group(
        target,
        Text(f"{len(schema.tables)} relations"),
        tables,
        Text("Use seed inspect --table NAME to see column and constraint details."),
    )


def plan_summary(plan: GenerationPlan) -> Group:
    tables = _grid("Table", "Rows", "Selection", "Parents")
    for table in plan.tables:
        parents = ", ".join(
            _label(edge.foreign_key.parent) + (" (existing)" if edge.source == "existing" else "")
            for edge in table.dependencies
        )
        tables.add_row(
            Text(_label(table.id)),
            f"{table.rows:,}",
            "Selected" if table.requested else "Required",
            Text(parents or "-"),
        )
    apply = "ready" if plan.compatibility["live"].executable else "blocked"
    export = "ready" if plan.compatibility["offline"].executable else "blocked"
    return Group(
        Text(
            f"{safe_text(plan.target.database)} · {safe_text(plan.target.schema_name)}",
            style="bold",
        ),
        Text(f"{plan.total_rows:,} planned rows across {len(plan.tables)} tables", style="bold"),
        tables,
        Text(f"Apply {apply} · Preview and export {export}"),
    )


def _cell(value: JsonValue) -> Text:
    return Text(
        json.dumps(value, ensure_ascii=False)
        if not isinstance(value, str)
        else safe_text(value) or '""'
    )


def preview_summary(sample: TableSample, planned: int, width: int) -> Group:
    title = Text(f"{_label(sample.table)} · {len(sample.rows)} of {planned:,} rows", style="bold")
    if not sample.rows:
        return Group(title, Text("No sample rows."))
    headers = tuple(safe_text(column.name) for column in sample.columns)
    if sum(max(8, min(20, len(header))) + 2 for header in headers) > width:
        table = _grid("Row", "Column", "Value")
        for index, record in enumerate(sample.rows, start=1):
            for position, (name, value) in enumerate(zip(headers, record, strict=True)):
                table.add_row(str(index) if position == 0 else "", Text(name), _cell(value))
    else:
        table = _grid(*headers)
        for record in sample.rows:
            table.add_row(*(_cell(value) for value in record))
    return Group(title, table)


def validation_summary(report: ValidationReport) -> Group:
    table = _grid("Check", "Status", "Rows checked")
    for name, step in report.stages().items():
        style = {"passed": "green", "failed": "red", "skipped": "dim"}[step.status]
        rows = "-" if step.rows_checked is None else f"{step.rows_checked:,}"
        table.add_row(name.capitalize(), Text(step.status.capitalize(), style=style), rows)
    summary = "Validation passed" if not report.status else "Validation failed"
    return Group(Text(summary, style="bold"), table)


def _counts(rows: Iterable[tuple[TableId, int]]) -> Table:
    table = _grid("Table", "Rows")
    for identifier, count in rows:
        table.add_row(Text(_label(identifier)), f"{count:,}")
    return table


def apply_summary(report: ApplyReport) -> Group:
    target = report.plan.target if report.plan else None
    destination = (
        Text(f"Database {safe_text(target.database)} · schema {safe_text(target.schema_name)}")
        if target
        else Text()
    )
    if report.dry_run:
        return Group(Text("Dry-run passed. No rows written.", style="bold"), destination)
    counts = report.insertion.counts if report.insertion else None
    if counts is None:
        return Group(Text("Apply finished.", style="bold"), destination)
    return Group(
        Text(f"Committed {sum(item.rows for item in counts):,} rows", style="bold green"),
        destination,
        _counts((item.table, item.rows) for item in counts),
    )


def export_summary(export: ExportResult) -> Group:
    total = sum(count for _, count in export.counts)
    return Group(
        Text(f"Exported {total:,} rows as {export.format.value.upper()}", style="bold green"),
        Text(f"Output directory {safe_text(str(export.directory))}"),
        Text(f"Files {', '.join(export.artifacts + ('manifest.json',))}"),
        _counts(export.counts),
    )
