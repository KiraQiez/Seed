"""Terminal and JSON projections for generation plans."""

import json

from seed.planning import GenerationPlan, PlanIssue


def plan_issues(report: GenerationPlan) -> list[dict[str, object]]:
    """Expose scoped issues with their affected modes."""
    return [
        issue_payload(issue, mode=mode)
        for mode, compatibility in report.compatibility.items()
        for issue in compatibility.issues
    ]


def issue_payload(issue: PlanIssue, *, mode: str | None = None) -> dict[str, object]:
    """Project a scoped issue without including supplied or generated values."""
    scope: dict[str, object] = {}
    if mode is not None:
        scope["mode"] = mode
    if issue.table is not None:
        scope["table"] = issue.table.model_dump(by_alias=True)
    if issue.column is not None:
        scope["column"] = issue.column
    if issue.constraint is not None:
        scope["constraint"] = issue.constraint
    if issue.ordinal is not None:
        scope["ordinal"] = issue.ordinal
    payload: dict[str, object] = {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity,
    }
    if scope:
        payload["scope"] = scope
    return payload


def plan_lines(report: GenerationPlan) -> list[str]:
    """Render counts, dependencies, bindings, and mode-specific diagnostics."""
    lines = [
        f"Plan for {json.dumps(report.target.database)} · {json.dumps(report.target.schema_name)}",
        f"{report.total_rows} planned rows across {len(report.tables)} tables",
    ]
    for table in report.tables:
        origin = "requested" if table.requested else "required"
        lines.append(f"{json.dumps(table.id.table)} · {table.rows} rows · {origin}")
        for dependency in table.dependencies:
            name = json.dumps(dependency.foreign_key.parent.table)
            lines.append(f"  Parent {name} · {dependency.source}")
        for mode, bindings in table.bindings.items():
            if bindings:
                choices = ", ".join(
                    f"{json.dumps(binding.column)}={binding.generator or binding.source}"
                    for binding in bindings
                )
                lines.append(f"  {mode} bindings · {choices}")
    for mode, compatibility in report.compatibility.items():
        lines.append(f"{mode} · {'available' if compatibility.executable else 'blocked'}")
        for issue in compatibility.issues:
            scope = f" {json.dumps(issue.table.table)}" if issue.table else ""
            lines.append(f"  {issue.code}{scope} · {issue.message}")
    return lines
