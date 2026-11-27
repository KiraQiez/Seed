"""Stream planned offline records without accessing a database."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial

from seed.config import GeneratorRule, SeedConfig
from seed.generation.record_checks import UniqueReservations, scalar_domain, value_matches
from seed.generation.relationships import ExistingKeys, ForeignKeys, ParentPools
from seed.generation.scalars import scalar_value
from seed.generation.streaming import (
    GeneratedRecord,
    GenerationError,
    RecordBatch,
    RunContext,
    Value,
    batches,
    retry_row,
    validate_batch_size,
)
from seed.metadata import ColumnSchema, DatabaseSchema, NumericBound, TableSchema
from seed.planning.bindings import Binding, choose_binding
from seed.planning.plan import GenerationPlan, Mode, PlanIssue, PlannedTable
from seed.planning.selection import MAX_ROWS

type InsertBatch = Callable[[TableSchema, RecordBatch, tuple[str, ...]], RecordBatch]
type ConflictProbe = Callable[[TableSchema, dict[str, Value]], bool]


@dataclass(frozen=True)
class LiveInputs:
    insert: InsertBatch
    existing: ExistingKeys | None = None
    conflicts: ConflictProbe | None = None


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
    yield from _generate(plan, schema, config, "offline", batch_size, None)


def generate_live_batches(
    plan: GenerationPlan,
    schema: DatabaseSchema,
    config: SeedConfig,
    inputs: LiveInputs,
) -> Iterator[RecordBatch]:
    """Generate live rows and correlate the committed-to-transaction batch from the adapter."""
    yield from _generate(plan, schema, config, "live", None, inputs)


def _generate(
    plan: GenerationPlan,
    schema: DatabaseSchema,
    config: SeedConfig,
    mode: Mode,
    batch_size: int | None,
    inputs: LiveInputs | None,
) -> Iterator[RecordBatch]:
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
    compatibility = plan.compatibility.get(mode)
    if compatibility is None or not compatibility.executable:
        raise GenerationError(
            PlanIssue(
                code="PLAN_BLOCKED",
                message=f"This plan cannot generate {mode} records.",
            )
        )
    size = plan.settings.batch_size if batch_size is None else batch_size
    validate_batch_size(size)
    yield from _table_batches(plan, schema, config, size, mode, inputs)


def _table_batches(
    plan: GenerationPlan,
    schema: DatabaseSchema,
    config: SeedConfig,
    size: int,
    mode: Mode,
    inputs: LiveInputs | None,
) -> Iterator[RecordBatch]:
    tables = {table.id: table for table in schema.tables}
    pools = ParentPools(plan, inputs.existing if inputs else None)
    for planned in plan.tables:
        if not planned.rows:
            continue
        table = tables.get(planned.id)
        if table is None:
            raise _binding_error(planned)
        columns = _prepare_columns(planned, table, config, plan.settings.locale, mode)
        identities = tuple(
            item.binding.column for item in columns if item.binding.source == "server_identity"
        )
        identity_columns = {item.binding.column: item.schema for item in columns}
        pending = frozenset(identities)
        writable = tuple(item for item in columns if item.binding.column not in pending)
        context = RunContext(plan.settings, planned.id)
        conflicts = inputs.conflicts if inputs else None
        foreign = ForeignKeys.prepare(planned, table, pools, context)
        uniqueness = UniqueReservations.for_table(
            table,
            config.rules.get(table.id.table, {}),
            pending=pending,
        )
        domains = {
            item.binding.column: scalar_domain(
                item.schema,
                item.binding.source,
                item.binding.generator,
                item.rule,
                item.bounds,
                context.settings.null_rate,
                planned.rows,
            )
            for item in writable
        }
        uniqueness.check_capacity(planned.id, domains, planned.rows)

        def draw(ordinal: int) -> GeneratedRecord | None:
            keys = foreign.draw()
            if keys is None:
                return None
            values = _candidate(writable, context, ordinal, keys)
            if (
                any(
                    not value_matches(
                        values[item.binding.column], item.schema, item.bounds, item.rule
                    )
                    for item in writable
                )
                or not foreign.contains(values)
                or (
                    table.primary_key
                    and any(
                        values[key] is None
                        for key in table.primary_key.columns
                        if key not in pending
                    )
                )
                or (conflicts is not None and conflicts(table, values))
                or not uniqueness.reserve(values)
            ):
                return None
            return GeneratedRecord(planned.id, ordinal, values)

        def accepted_rows() -> Iterator[GeneratedRecord]:
            for ordinal in range(planned.rows):
                record = retry_row(planned.id, ordinal, partial(draw, ordinal))
                foreign.accept(record.values)
                yield record

        for batch in batches(accepted_rows(), size):
            completed = inputs.insert(table, batch, identities) if inputs is not None else batch
            if len(completed) != len(batch):
                raise _binding_error(planned)
            for original, record in zip(batch, completed, strict=True):
                if (
                    record.table != original.table
                    or record.ordinal != original.ordinal
                    or any(
                        name not in record.values
                        or record.values[name] is None
                        or not value_matches(record.values[name], identity_columns[name], (), None)
                        for name in identities
                    )
                ):
                    raise _binding_error(planned)
                pools.accept(record)
            yield completed
        pools.finish(planned)


def _prepare_columns(
    planned: PlannedTable,
    table: TableSchema,
    config: SeedConfig,
    locale: str,
    mode: Mode,
) -> tuple[_Column, ...]:
    rules = config.rules.get(table.id.table, {})
    columns = {column.name: column for column in table.columns}
    bindings = planned.bindings.get(mode)
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
