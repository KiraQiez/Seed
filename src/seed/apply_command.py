"""Coordinate the CLI confirmation boundary with one guarded apply session."""

from collections.abc import Callable
from dataclasses import dataclass

from seed.apply import (
    ApplyError,
    apply_preflight,
    check_target,
    confirm_apply,
    preflight_lines,
    validate_apply_options,
)
from seed.config import ConfigError, resolve_database_url
from seed.database import DatabaseError, open_session, parse_database_url
from seed.insertion import InsertionResult, execute_apply
from seed.plan_output import issue_payload
from seed.planning import GenerationPlan, PlanIssue, PlanRequest


@dataclass(frozen=True)
class ApplyReport:
    status: int
    dry_run: bool
    plan: GenerationPlan | None
    insertion: InsertionResult | None
    issues: list[dict[str, object]]

    def payload(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "plan": self.plan.model_dump(mode="json", by_alias=True) if self.plan else None,
            "insertion": (
                self.insertion.model_dump(mode="json", by_alias=True, exclude_none=True)
                if self.insertion
                else None
            ),
        }


def run_apply(
    request: PlanRequest,
    *,
    yes: bool,
    dry_run: bool,
    interactive: bool,
    prompt: Callable[[], str],
    show_target: Callable[[str], None],
) -> ApplyReport:
    """Preflight, show the authorized target, and require approval before writing."""
    plan = None
    insertion = None if dry_run else InsertionResult(outcome="not_started")
    failure: PlanIssue | None = None
    status = 0
    writing = False
    try:
        validate_apply_options(yes=yes, dry_run=dry_run)
        config = request.load()
        url = parse_database_url(resolve_database_url(config))
        check_target(config, url)
        with open_session(url, config.database) as connection:
            approved = apply_preflight(connection, url, config, request)
            plan = approved.plan
            show_target("\n".join(preflight_lines(approved)))
            if not dry_run:
                confirm_apply(yes=yes, interactive=interactive, prompt=prompt)
                writing = True
                result = execute_apply(connection, url, config, request, approved)
                status, insertion, failure = result.status, result.insertion, result.issue
    except ConfigError as error:
        status, failure = 2, PlanIssue(code="CONFIG_INVALID", message=str(error))
    except DatabaseError as error:
        if isinstance(error, ApplyError) and error.plan is not None:
            plan = error.plan
        status, failure = error.status, PlanIssue(code=error.code, message=str(error))
    except KeyboardInterrupt:
        if writing:
            status = 6
            insertion = InsertionResult(outcome="unknown")
            failure = PlanIssue(
                code="COMMIT_OUTCOME_UNKNOWN",
                message="Apply was interrupted. Verify the database outcome before retrying.",
            )
        else:
            status = 130
            failure = PlanIssue(code="INTERRUPTED", message="Apply was interrupted before writing.")

    issues = (
        [issue_payload(issue, mode="live") for issue in plan.compatibility["live"].issues]
        if plan is not None
        else []
    )
    if failure is not None:
        issues.append(issue_payload(failure))
    return ApplyReport(status, dry_run, plan, insertion, issues)
