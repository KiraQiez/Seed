"""Insert generated batches inside one guarded PostgreSQL transaction."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import URL, Connection, MetaData, Table, insert, literal_column, select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from seed.apply import ApprovedPlan, begin_guarded_write, rollback
from seed.config import SeedConfig
from seed.generation import LiveInputs, generate_live_batches
from seed.metadata import Metadata, TableId, TableSchema
from seed.planning import PlanIssue, PlannedDependency, PlanRequest
from seed.relationships import MAX_EXISTING_KEYS, KeyTuple
from seed.streaming import GeneratedRecord, GenerationError, RecordBatch, Value

type Outcome = Literal["not_started", "rolled_back", "committed", "unknown"]


class InsertedCount(Metadata):
    table: TableId
    rows: int


class InsertionResult(Metadata):
    outcome: Outcome
    counts: tuple[InsertedCount, ...] | None = None


@dataclass(frozen=True)
class WriteResult:
    status: int
    insertion: InsertionResult
    issue: PlanIssue | None = None


class PostgreSQLWriter:
    """Bind values into the reflected SQL type and correlate returned identities."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._metadata = MetaData()
        self._tables: dict[TableId, Table] = {}

    def table(self, identifier: TableId) -> Table:
        table = self._tables.get(identifier)
        if table is None:
            table = Table(
                identifier.table,
                self._metadata,
                schema=identifier.schema_name,
                autoload_with=self.connection,
                postgresql_ignore_search_path=True,
                resolve_fks=False,
                quote=True,
                quote_schema=True,
            )
            self._tables[identifier] = table
        return table

    def write(
        self,
        model: TableSchema,
        batch: RecordBatch,
        identities: tuple[str, ...],
    ) -> RecordBatch:
        """Return records in input order with any assigned server keys."""
        table = self.table(model.id)
        returned = [table.c[name] for name in identities]
        base = insert(table)
        statement = (
            base.returning(*returned, sort_by_parameter_order=True)
            if returned
            else base.returning(literal_column("1"))
        )
        parameters = [record.values for record in batch]
        ordered_batches = getattr(
            self.connection.dialect, "insert_executemany_returning_sort_by_parameter_order", False
        )
        if not parameters[0]:
            rows = [self.connection.execute(statement.values()).one() for _ in batch]
        elif len(batch) == 1:
            rows = [self.connection.execute(statement, parameters[0]).one()]
        elif identities and not ordered_batches:
            rows = [self.connection.execute(statement, row).one() for row in parameters]
        else:
            rows = list(self.connection.execute(statement, parameters))
        if len(rows) != len(batch):
            raise GenerationError(
                PlanIssue(
                    code="INSERT_COUNT_MISMATCH",
                    message="PostgreSQL returned an unexpected row count.",
                    table=model.id,
                )
            )
        return tuple(
            GeneratedRecord(
                record.table,
                record.ordinal,
                {
                    **record.values,
                    **dict(
                        zip(
                            identities,
                            cast(tuple[Value, ...], tuple(row)[: len(identities)]),
                            strict=True,
                        )
                    ),
                },
            )
            for record, row in zip(batch, rows, strict=True)
        )

    def load_existing(self, edge: PlannedDependency) -> Iterator[KeyTuple]:
        """Read one bounded, stable set of whole non-null referenced keys."""
        foreign = edge.foreign_key
        table = self.table(foreign.parent)
        columns = [table.c[name] for name in foreign.parent_columns]
        statement = (
            select(*columns)
            .where(*(column.is_not(None) for column in columns))
            .order_by(*columns)
            .limit(MAX_EXISTING_KEYS)
        )
        for row in self.connection.execute(statement):
            yield cast(KeyTuple, tuple(row))

    def conflicts(self, model: TableSchema, values: dict[str, Value]) -> bool:
        """Probe only existing database-backed keys with typed indexed predicates."""
        specs: list[tuple[tuple[str, ...], bool]] = []
        if model.primary_key:
            specs.append((model.primary_key.columns, False))
        specs.extend(
            (key.columns, bool(key.nulls_distinct)) for key in model.unique_keys if key.supported
        )
        table = self.table(model.id)
        for columns, nulls_distinct in specs:
            if any(name not in values for name in columns):
                continue
            if nulls_distinct and any(values[name] is None for name in columns):
                continue
            predicates = [
                table.c[name].is_(None) if values[name] is None else table.c[name] == values[name]
                for name in columns
            ]
            if self.connection.scalar(
                select(select(literal_column("1")).select_from(table).where(*predicates).exists())
            ):
                return True
        return False


def execute_apply(
    connection: Connection,
    url: URL,
    config: SeedConfig,
    request: PlanRequest,
    approved: ApprovedPlan,
) -> WriteResult:
    """Hold all locks through one commit and expose counts only after acknowledgement."""
    try:
        transaction = begin_guarded_write(connection, url, config, request, approved)
    except KeyboardInterrupt:
        return _write_error(
            "not_started", "INTERRUPTED", "Apply was interrupted before writing.", 130
        )
    writer = PostgreSQLWriter(connection)
    counts: dict[TableId, int] = {}
    inputs = LiveInputs(
        insert=writer.write,
        existing=writer.load_existing,
        conflicts=writer.conflicts if config.safety.allow_existing_data else None,
    )
    try:
        for batch in generate_live_batches(
            approved.plan, approved.inspection.schema, config, inputs
        ):
            identifier = batch[0].table
            counts[identifier] = counts.get(identifier, 0) + len(batch)
    except GenerationError as error:
        rollback(transaction)
        return WriteResult(4, InsertionResult(outcome="rolled_back"), error.issue)
    except SQLAlchemyError:
        rollback(transaction)
        return _write_error("rolled_back", "INSERT_FAILED", "Could not insert the planned rows.")
    except KeyboardInterrupt:
        rollback(transaction)
        return _write_error(
            "rolled_back", "INTERRUPTED", "Apply was interrupted before commit.", 130
        )
    except Exception:
        rollback(transaction)
        raise
    issue = commit_outcome(transaction.commit)
    if issue is not None:
        rollback(transaction)
        return issue
    return WriteResult(
        0,
        InsertionResult(
            outcome="committed",
            counts=tuple(InsertedCount(table=table, rows=rows) for table, rows in counts.items()),
        ),
    )


def commit_outcome(commit: Callable[[], None]) -> WriteResult | None:
    """Differentiate an acknowledged server rejection from an ambiguous commit."""
    try:
        commit()
    except DBAPIError as error:
        sqlstate = getattr(error.orig, "sqlstate", "") or ""
        if not error.connection_invalidated and (
            sqlstate.startswith("23") or sqlstate in {"40001", "40P01"}
        ):
            return _write_error(
                "rolled_back", "COMMIT_REJECTED", "PostgreSQL rejected the transaction."
            )
        return _unknown_commit()
    except (SQLAlchemyError, KeyboardInterrupt, OSError):
        return _unknown_commit()
    return None


def _unknown_commit() -> WriteResult:
    return _write_error(
        "unknown",
        "COMMIT_OUTCOME_UNKNOWN",
        "Commit was not acknowledged. Verify the database outcome before retrying.",
    )


def _write_error(outcome: Outcome, code: str, message: str, status: int = 6) -> WriteResult:
    return WriteResult(
        status, InsertionResult(outcome=outcome), PlanIssue(code=code, message=message)
    )
