"""Coordinate offline generation and the completed export result."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from seed.config import ConfigError, SeedConfig
from seed.database import DatabaseError
from seed.dataset import DatasetColumn, dataset_columns, dataset_header
from seed.export_files import ExportFileError, export_directory
from seed.export_sql import write_sql
from seed.export_tabular import write_csv, write_json
from seed.generation import generate_batches
from seed.metadata import DatabaseSchema, TableId, TableSchema
from seed.plan_output import issue_payload
from seed.planning import GenerationPlan, PlanIssue, PlannedTable, PlanRequest
from seed.streaming import GeneratedRecord, GenerationError


class ExportFormat(StrEnum):
    SQL = "sql"
    CSV = "csv"
    JSON = "json"


@dataclass(frozen=True)
class _TableExport:
    planned: PlannedTable
    schema: TableSchema
    columns: tuple[DatasetColumn, ...]
    file: str


@dataclass(frozen=True)
class ExportResult:
    format: ExportFormat
    directory: Path
    artifacts: tuple[str, ...]
    counts: tuple[tuple[TableId, int], ...]

    def payload(self) -> dict[str, object]:
        return {
            "format": self.format.value,
            "directory": str(self.directory),
            "manifest": "manifest.json",
            "artifacts": self.artifacts,
            "counts": [
                {"table": table.model_dump(by_alias=True), "rows": count}
                for table, count in self.counts
            ],
        }


@dataclass(frozen=True)
class ExportReport:
    status: int
    result: ExportResult | None
    issues: tuple[dict[str, object], ...]


def _verified_rows(
    table: PlannedTable, records: Iterator[GeneratedRecord]
) -> Iterator[GeneratedRecord]:
    for ordinal in range(table.rows):
        record = next(records, None)
        if record is None or record.table != table.id or record.ordinal != ordinal:
            raise ExportFileError("EXPORT_FAILED", "Generated rows did not match the export plan.")
        yield record


def _save_export(
    path: Path,
    format: ExportFormat,
    plan: GenerationPlan,
    schema: DatabaseSchema,
    config: SeedConfig,
) -> ExportResult:
    metadata = {table.id: table for table in schema.tables}
    tables = tuple(
        _TableExport(
            table,
            metadata[table.id],
            dataset_columns(metadata[table.id]),
            f"table-{index:04}.csv" if format == ExportFormat.CSV else f"dataset.{format.value}",
        )
        for index, table in enumerate(plan.tables, start=1)
    )
    records = (record for batch in generate_batches(plan, schema, config) for record in batch)
    with export_directory(path) as output:
        if format == ExportFormat.CSV:
            for table in tables:
                with output.artifact(table.file) as stream:
                    write_csv(stream, table.columns, _verified_rows(table.planned, records))
        else:
            with output.artifact(f"dataset.{format.value}") as stream:
                if format == ExportFormat.JSON:
                    write_json(
                        stream,
                        (
                            (
                                table.planned.id,
                                table.columns,
                                _verified_rows(table.planned, records),
                            )
                            for table in tables
                        ),
                    )
                else:
                    write_sql(
                        stream,
                        (
                            (table.schema, _verified_rows(table.planned, records))
                            for table in tables
                        ),
                    )
        if next(records, None) is not None:
            raise ExportFileError("EXPORT_FAILED", "Generated rows exceeded the export plan.")
        output.publish(
            {
                "version": 1,
                "format": format.value,
                "schema_fingerprint": plan.schema_fingerprint,
                "tables": [
                    {
                        **dataset_header(table.planned.id, table.columns),
                        "rows": table.planned.rows,
                        "file": table.file,
                    }
                    for table in tables
                ],
            }
        )
    artifacts: Iterable[str] = (
        (table.file for table in tables)
        if format == ExportFormat.CSV
        else (f"dataset.{format.value}",)
    )
    return ExportResult(
        format,
        path,
        tuple(artifacts),
        tuple((table.planned.id, table.planned.rows) for table in tables),
    )


def run_export(request: PlanRequest, format: ExportFormat, output: Path) -> ExportReport:
    """Render one validated offline snapshot with redacted diagnostics."""
    diagnostics: tuple[dict[str, object], ...] = ()
    try:
        config = request.load()
        schema, plan = request.snapshot(config)
        offline = plan.compatibility["offline"]
        diagnostics = tuple(issue_payload(issue, mode="offline") for issue in offline.issues)
        if not offline.executable:
            return ExportReport(4, None, diagnostics)
        return ExportReport(0, _save_export(output, format, plan, schema, config), diagnostics)
    except ConfigError as error:
        status, issue = 2, PlanIssue(code="CONFIG_INVALID", message=str(error))
    except DatabaseError as error:
        status, issue = error.status, PlanIssue(code=error.code, message=str(error))
    except GenerationError as error:
        return ExportReport(4, None, (*diagnostics, issue_payload(error.issue, mode="offline")))
    except ExportFileError as error:
        status, issue = 6, PlanIssue(code=error.code, message=str(error))
    except KeyboardInterrupt:
        status, issue = 130, PlanIssue(code="INTERRUPTED", message="Export was interrupted.")
    return ExportReport(status, None, (*diagnostics, issue_payload(issue)))
