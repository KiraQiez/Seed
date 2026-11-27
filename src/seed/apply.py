"""Apply safety checks and write orchestration."""

import json
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import URL, Connection, text
from sqlalchemy.exc import SAWarning, SQLAlchemyError

from seed.config import ConfigError, SeedConfig
from seed.database import DatabaseError, read_snapshot
from seed.inspection import requested_tables
from seed.metadata import Inspection, TableId
from seed.planning import GenerationPlan, PlanRequest, build_plan
from seed.schema import reflect_schema


class ApplyError(DatabaseError):
    """A safe preflight or transaction refusal."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 5,
        *,
        plan: GenerationPlan | None = None,
    ) -> None:
        super().__init__(code, message, status)
        self.plan = plan


@dataclass(frozen=True)
class ApprovedPlan:
    inspection: Inspection
    plan: GenerationPlan
    backend: tuple[int, datetime, str, str] = field(repr=False)

    @property
    def targets(self) -> tuple[TableId, ...]:
        return tuple(table.id for table in self.plan.tables if table.rows)

    @property
    def reused_parents(self) -> tuple[TableId, ...]:
        seen = {
            edge.foreign_key.parent
            for table in self.plan.tables
            for edge in table.dependencies
            if edge.source == "existing"
        }
        return tuple(sorted(seen, key=lambda table: (table.schema_name, table.table)))


def check_target(config: SeedConfig, url: URL) -> None:
    """Require an independently configured safe environment and exact URL target."""
    target = config.safety.target
    if config.safety.environment not in {"development", "test"} or target is None:
        raise ApplyError("TARGET_REQUIRED", "Apply requires a development or test target.")
    if (target.host, target.port, target.database, target.schema_name) != (
        url.host,
        url.port,
        url.database,
        config.database.schema_name,
    ):
        raise ApplyError(
            "TARGET_MISMATCH", "Connected database does not match the configured write target."
        )


def apply_preflight(
    connection: Connection,
    url: URL,
    config: SeedConfig,
    request: PlanRequest,
) -> ApprovedPlan:
    """Read the authorized target and plan without writing or retaining a transaction."""
    check_target(config, url)
    try:
        with read_snapshot(connection):
            check_server(connection, url)
            backend = backend_identity(connection)
            inspection = inspect_for_apply(connection, url, config)
            requested_tables(config.database.schema_name, request.filters)
            plan = build_plan(config, inspection.schema, request.filters, request.rows)
            if not plan.compatibility["live"].executable:
                raise ApplyError("PLAN_BLOCKED", "This plan cannot be applied.", 4, plan=plan)
            if plan.total_rows <= 0:
                raise ApplyError(
                    "NO_ROWS_PLANNED", "Apply requires a positive row count.", plan=plan
                )
            approved = ApprovedPlan(inspection, plan, backend)
            check_empty_targets(connection, config, approved)
            return approved
    except SQLAlchemyError:
        raise ApplyError("PREFLIGHT_FAILED", "Could not verify the target for apply.") from None


def inspect_for_apply(connection: Connection, url: URL, config: SeedConfig) -> Inspection:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SAWarning)
        try:
            return reflect_schema(connection, url, config.database.schema_name)
        except (LookupError, ValueError, NotImplementedError):
            raise ApplyError(
                "SCHEMA_INSPECTION_FAILED", "PostgreSQL metadata could not be normalized.", 4
            ) from None


def backend_identity(connection: Connection) -> tuple[int, datetime, str, str]:
    row = connection.execute(
        text(
            "SELECT pid, backend_start, current_user, session_user "
            "FROM pg_catalog.pg_stat_activity WHERE pid = pg_catalog.pg_backend_pid()"
        )
    ).one()
    return int(row[0]), row[1], str(row[2]), str(row[3])


def check_server(connection: Connection, url: URL) -> None:
    if connection.scalar(text("SELECT pg_catalog.current_database()")) != url.database:
        raise ApplyError(
            "TARGET_MISMATCH", "Connected database does not match the configured write target."
        )
    if connection.scalar(text("SHOW session_replication_role")) != "origin":
        raise ApplyError("UNSAFE_REPLICATION_ROLE", "PostgreSQL must enforce ordinary constraints.")


def qualified(connection: Connection, table: TableId) -> str:
    """Compose a schema-qualified identifier from trusted metadata."""
    quote = connection.dialect.identifier_preparer.quote_identifier
    return f"{quote(table.schema_name)}.{quote(table.table)}"


def check_empty_targets(connection: Connection, config: SeedConfig, approved: ApprovedPlan) -> None:
    if config.safety.allow_existing_data:
        return
    for table in approved.targets:
        if connection.scalar(
            text(f"SELECT EXISTS (SELECT 1 FROM ONLY {qualified(connection, table)})")
        ):
            raise ApplyError(
                "TARGET_NOT_EMPTY",
                "A target table contains rows and append is disabled.",
                plan=approved.plan,
            )


def preflight_lines(approved: ApprovedPlan) -> list[str]:
    target = approved.plan.target
    lines = [
        f"Apply target {json.dumps(target.host)}:{target.port} "
        f"database {json.dumps(target.database)}, schema {json.dumps(target.schema_name)}",
        f"{approved.plan.total_rows} planned rows",
    ]
    for table in approved.plan.tables:
        if table.rows:
            lines.append(f"  {json.dumps(table.id.table)} · {table.rows} rows")
    lines.extend(
        f"  {json.dumps(parent.table)} · reuse existing keys" for parent in approved.reused_parents
    )
    return lines


def validate_apply_options(*, yes: bool, dry_run: bool) -> None:
    if yes and dry_run:
        raise ConfigError("Use either --dry-run or --yes.")


def confirm_apply(*, yes: bool, interactive: bool, prompt: Callable[[], str]) -> None:
    """Require affirmative approval, including when terminal input ends."""
    if yes:
        return
    if not interactive:
        raise ApplyError("CONFIRMATION_REQUIRED", "Use --yes to approve a non-interactive apply.")
    try:
        answer = prompt()
    except EOFError:
        answer = ""
    if answer.strip().lower() not in {"y", "yes"}:
        raise ApplyError("CANCELLED", "Apply was not confirmed.")
