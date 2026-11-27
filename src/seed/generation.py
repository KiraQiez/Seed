"""Stream planned offline records without accessing a database."""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial

from seed.bindings import Binding, choose_binding
from seed.config import GeneratorRule, SeedConfig
from seed.metadata import ColumnSchema, DatabaseSchema, NumericBound, TableSchema
from seed.planning import GenerationPlan, PlanIssue, PlannedTable
from seed.relationships import ForeignKeys, ParentPools
from seed.scalars import scalar_value
from seed.selection import MAX_ROWS
from seed.streaming import (
    GeneratedRecord,
    GenerationError,
    RecordBatch,
    RunContext,
    Value,
    batches,
    retry_row,
)


@dataclass(frozen=True)
class _Column:
    binding: Binding
    schema: ColumnSchema
    rule: GeneratorRule | None
    bounds: tuple[NumericBound, ...]


def generate_batches(
    plan: GenerationPlan,
    schema: DatabaseSchema,
    config: SeedConfig,
    *,
    batch_size: int | None = None,
) -> Iterator[RecordBatch]:
    """Generate the planned records in deterministic, bounded single-table batches."""
    if (
        plan.schema_fingerprint != schema.fingerprint
        or plan.target != schema.target
        or not 0 <= plan.total_rows <= MAX_ROWS
        or any(table.rows < 0 for table in plan.tables)
        or sum(table.rows for table in plan.tables) != plan.total_rows
    ):
        raise GenerationError(
            PlanIssue(
                code="INVALID_PLAN",
                message="The plan does not match the supplied schema or row limits.",
            )
        )
    mode = plan.compatibility.get("offline")
    if mode is None or not mode.executable:
        raise GenerationError(
            PlanIssue(
                code="PLAN_BLOCKED",
                message="This plan cannot generate offline records.",
            )
        )
    size = plan.settings.batch_size if batch_size is None else batch_size
    yield from batches(_records(plan, schema, config), size)


def _records(
    plan: GenerationPlan,
    schema: DatabaseSchema,
    config: SeedConfig,
) -> Iterator[GeneratedRecord]:
    tables = {table.id: table for table in schema.tables}
    pools = ParentPools(plan)
    for planned in plan.tables:
        if not planned.rows:
            continue
        table = tables.get(planned.id)
        if table is None:
            raise _binding_error(planned)
        columns = _prepare_columns(planned, table, config, plan.settings.locale)
        context = RunContext(plan.settings, planned.id)
        foreign = ForeignKeys.prepare(planned, table, pools, context)

        def draw(ordinal: int) -> GeneratedRecord | None:
            keys = foreign.draw()
            if keys is None:
                return None
            values = _candidate(columns, context, ordinal, keys)
            return GeneratedRecord(planned.id, ordinal, values)

        for ordinal in range(planned.rows):
            record = retry_row(planned.id, ordinal, partial(draw, ordinal))
            foreign.accept(record.values)
            pools.accept(record)
            yield record
        pools.finish(planned)


def _prepare_columns(
    planned: PlannedTable,
    table: TableSchema,
    config: SeedConfig,
    locale: str,
) -> tuple[_Column, ...]:
    rules = config.rules.get(table.id.table, {})
    columns = {column.name: column for column in table.columns}
    bindings = planned.bindings.get("offline")
    if bindings is None or tuple(binding.column for binding in bindings) != tuple(columns):
        raise _binding_error(planned)
    if rules.keys() - columns.keys():
        raise _binding_error(planned)
    result: list[_Column] = []
    for binding in bindings:
        column = columns[binding.column]
        rule = rules.get(binding.column)
        bounds = tuple(
            bound for check in table.checks for bound in check.bounds if bound.column == column.name
        )
        if binding.source == "generator":
            expected, compatible = choose_binding(column, rule, locale, bounds)
            if not compatible or binding != expected:
                raise _binding_error(planned, column.name)
        elif rule is not None:
            raise _binding_error(planned, column.name)
        if binding.source != "omit":
            result.append(_Column(binding, column, rule, bounds))
    return tuple(result)


def _candidate(
    columns: tuple[_Column, ...],
    context: RunContext,
    ordinal: int,
    keys: dict[str, Value],
) -> dict[str, Value]:
    values: dict[str, Value] = {}
    for item in columns:
        binding = item.binding
        if binding.source in {"foreign_key", "null"}:
            values[binding.column] = keys[binding.column]
        elif binding.source == "explicit_identity":
            values[binding.column] = ordinal + 1
        else:
            assert binding.generator is not None
            values[binding.column] = scalar_value(
                context, item.schema, binding.generator, item.rule, item.bounds
            )
    return values


def _binding_error(planned: PlannedTable, column: str | None = None) -> GenerationError:
    return GenerationError(
        PlanIssue(
            code="INVALID_PLAN_BINDING",
            message="A planned binding does not match generation inputs.",
            table=planned.id,
            column=column,
        )
    )
