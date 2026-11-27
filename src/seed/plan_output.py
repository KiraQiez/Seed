"""Terminal and JSON projections for generation plans."""

import json

from seed.planning import GenerationPlan, PlanIssue


def plan_issues(report: GenerationPlan) -> list[dict[str, object]]:
    """Expose scoped issues with their affected modes."""
    issues: list[dict[str, object]] = []
    for mode, compatibility in report.compatibility.items():
        for issue in compatibility.issues:
            issues.append(
                {
                    "code": issue.code,
                    "message": issue.message,
                    "severity": issue.severity,
                    "scope": _scope(issue, mode),
                }
            )
    return issues


def _scope(issue: PlanIssue, mode: str) -> dict[str, object]:
    scope: dict[str, object] = {"mode": mode}
    if issue.table is not None:
        scope["table"] = issue.table.model_dump(by_alias=True)
    if issue.column is not None:
        scope["column"] = issue.column
    if issue.constraint is not None:
        scope["constraint"] = issue.constraint
    return scope


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
