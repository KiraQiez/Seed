"""Run staged configuration, planning, and offline dataset checks."""

from dataclasses import dataclass
from typing import Literal

from seed.config import ConfigError, resolve_database_url
from seed.database import DatabaseError, parse_database_url
from seed.generation import generate_batches
from seed.plan_output import issue_payload, plan_issues
from seed.planning import PlanIssue, PlanRequest
from seed.streaming import GenerationError

type StageStatus = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True)
class Stage:
    status: StageStatus
    issues: tuple[dict[str, object], ...] = ()
    rows_checked: int | None = None

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {"status": self.status, "issues": list(self.issues)}
        if self.rows_checked is not None:
            result["rows_checked"] = self.rows_checked
        return result


_PASSED = Stage("passed")
_SKIPPED = Stage("skipped")


@dataclass(frozen=True)
class ValidationReport:
    status: int
    config: Stage
    plan: Stage = _SKIPPED
    dataset: Stage = _SKIPPED

    def stages(self) -> dict[str, Stage]:
        return {"config": self.config, "plan": self.plan, "dataset": self.dataset}

    def payload(self) -> dict[str, object]:
        return {name: stage.payload() for name, stage in self.stages().items()}

    def issues(self) -> list[dict[str, object]]:
        return [issue for stage in self.stages().values() for issue in stage.issues]


def validate(request: PlanRequest, *, dataset: bool) -> ValidationReport:
    """Validate prerequisites in order and stream complete offline batches on request."""
    try:
        config = request.load()
        url = parse_database_url(resolve_database_url(config))
    except ConfigError as error:
        return ValidationReport(2, _failed("CONFIG_INVALID", str(error)))

    try:
        schema, plan = request.snapshot(config, url=url)
    except ConfigError as error:
        return ValidationReport(2, _failed("CONFIG_INVALID", str(error)))
    except DatabaseError as error:
        return ValidationReport(error.status, _PASSED, _failed(error.code, str(error)))

    diagnostics = tuple(plan_issues(plan))
    if not plan.executable:
        return ValidationReport(4, _PASSED, Stage("failed", diagnostics))
    planned = Stage("passed", diagnostics)
    if not dataset:
        return ValidationReport(0, _PASSED, planned)
    if not plan.compatibility["offline"].executable:
        return ValidationReport(
            4,
            _PASSED,
            planned,
            _failed(
                "PLAN_BLOCKED",
                "This plan cannot generate offline records.",
                rows_checked=0,
            ),
        )

    rows_checked = 0
    try:
        for batch in generate_batches(plan, schema, config):
            rows_checked += len(batch)
    except GenerationError as error:
        checked = Stage("failed", (issue_payload(error.issue, mode="offline"),), rows_checked)
        return ValidationReport(4, _PASSED, planned, checked)
    return ValidationReport(0, _PASSED, planned, Stage("passed", rows_checked=rows_checked))


def _failed(code: str, message: str, *, rows_checked: int | None = None) -> Stage:
    return Stage("failed", (issue_payload(PlanIssue(code=code, message=message)),), rows_checked)
