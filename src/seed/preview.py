"""Sample the offline dataset while retaining only the requested prefixes."""

from dataclasses import dataclass

from seed.config import ConfigError, SeedConfig
from seed.database import DatabaseError
from seed.dataset import JsonRow, TableSample, dataset_columns, dataset_row
from seed.generation import generate_batches
from seed.metadata import DatabaseSchema, TableId
from seed.plan_output import issue_payload, plan_issues
from seed.planning import GenerationPlan, PlanIssue, PlanRequest
from seed.streaming import GenerationError


@dataclass(frozen=True)
class PreviewReport:
    status: int
    plan: GenerationPlan | None = None
    tables: tuple[TableSample, ...] = ()
    issues: tuple[dict[str, object], ...] = ()

    def payload(self) -> dict[str, object] | None:
        if self.plan is None:
            return None
        return {
            "plan": self.plan.model_dump(mode="json", by_alias=True),
            "tables": [table.payload() for table in self.tables],
        }


def preview(request: PlanRequest, limit: int) -> PreviewReport:
    """Build and sample one schema snapshot through the read-only boundary."""
    try:
        if not 1 <= limit <= 100:
            raise ConfigError("--limit must be from 1 to 100.")
        config = request.load()
        schema, plan = request.snapshot(config)
    except ConfigError as error:
        return _failure(2, "CONFIG_INVALID", str(error))
    except DatabaseError as error:
        return _failure(error.status, error.code, str(error))

    diagnostics = tuple(plan_issues(plan))
    if not plan.compatibility["offline"].executable:
        return PreviewReport(4, plan, issues=diagnostics)
    try:
        samples = sample_tables(plan, schema, config, limit)
    except GenerationError as error:
        return PreviewReport(
            4,
            plan,
            issues=(*diagnostics, issue_payload(error.issue, mode="offline")),
        )
    return PreviewReport(0, plan, samples, diagnostics)


def _failure(status: int, code: str, message: str) -> PreviewReport:
    return PreviewReport(status, issues=(issue_payload(PlanIssue(code=code, message=message)),))


def _bounded_plan(plan: GenerationPlan, limit: int) -> GenerationPlan:
    counts = {table.id: table.rows for table in plan.tables}
    sizes = {table.id: min(limit, table.rows) for table in plan.tables if table.requested}
    for table in reversed(plan.tables):
        if sizes.get(table.id):
            for edge in table.dependencies:
                if edge.source == "generated":
                    parent = edge.foreign_key.parent
                    sizes[parent] = counts[parent]
    return plan.model_copy(
        update={
            "tables": tuple(
                table.model_copy(update={"rows": sizes.get(table.id, 0)}) for table in plan.tables
            ),
            "total_rows": sum(sizes.values()),
        }
    )


def sample_tables(
    plan: GenerationPlan,
    schema: DatabaseSchema,
    config: SeedConfig,
    limit: int,
) -> tuple[TableSample, ...]:
    """Generate only requested prefixes and their complete parent pools."""
    metadata = {table.id: table for table in schema.tables}
    columns = {
        table.id: dataset_columns(metadata[table.id]) for table in plan.tables if table.requested
    }
    rows: dict[TableId, list[JsonRow]] = {table: [] for table in columns}
    for batch in generate_batches(_bounded_plan(plan, limit), schema, config):
        table = batch[0].table
        if table in rows:
            output = rows[table]
            output.extend(
                dataset_row(record, columns[table]) for record in batch[: limit - len(output)]
            )
    return tuple(
        TableSample(table, descriptor, tuple(rows[table])) for table, descriptor in columns.items()
    )
