"""Terminal entry point for Seed."""

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text
from typer._click.exceptions import UsageError

from seed import __version__
from seed.config import ConfigError
from seed.database import DatabaseError
from seed.initialize import initialize_config
from seed.inspection import inspect_database
from seed.inspection_output import inspection_lines
from seed.plan_output import plan_issues, plan_lines
from seed.planning import PlanRequest, plan_database
from seed.preview import preview as preview_request
from seed.validation import validate as validate_request

app = typer.Typer(
    help="Generate synthetic data for development and testing.",
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def result(message: str) -> None:
    """Write a result to stdout."""
    Console().print(Text(message))


def diagnostic(message: str) -> None:
    """Write a diagnostic to stderr."""
    Console(stderr=True).print(Text(message))


@app.callback()
def root(
    version: bool = typer.Option(
        False, "--version", is_eager=True, help="Show the package version."
    ),
) -> None:
    """Work with Seed configurations and datasets."""
    if version:
        result(__version__)
        raise typer.Exit()


@app.command()
def init(
    config: Annotated[Path, typer.Option("--config", help="Starter configuration path.")] = Path(
        "./seed.toml"
    ),
    as_json: Annotated[bool, typer.Option("--json", help="Emit a JSON result.")] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Show additional diagnostics.")
    ] = False,
) -> None:
    """Create a starter configuration."""
    try:
        created = initialize_config(config)
    except (OSError, ConfigError) as error:
        code = "CONFIG_INVALID" if isinstance(error, ConfigError) else "INIT_FAILED"
        status = 2 if isinstance(error, ConfigError) else 6
        if as_json:
            _json_response(
                "init",
                status,
                None,
                [
                    {"code": code, "severity": "error", "message": str(error)},
                ],
            )
        else:
            diagnostic(str(error))
        raise typer.Exit(status) from None

    if verbose:
        diagnostic("Created a starter configuration." if created else "Existing file preserved.")
    if as_json:
        _json_response("init", 0, {"path": str(config), "created": created}, [])
    else:
        result("Created seed configuration." if created else "Seed configuration already exists.")


@app.command()
def inspect(
    config: Annotated[Path, typer.Option("--config", help="Configuration path.")] = Path(
        "./seed.toml"
    ),
    schema: Annotated[str | None, typer.Option("--schema", help="Exact schema name.")] = None,
    table: Annotated[
        list[str] | None, typer.Option("--table", help="Limit displayed tables.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit a JSON result.")] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Show additional diagnostics.")
    ] = False,
) -> None:
    """Inspect one PostgreSQL schema in a read-only transaction."""
    try:
        report = inspect_database(config, schema, table or [])
    except (ConfigError, DatabaseError) as error:
        code = error.code if isinstance(error, DatabaseError) else "CONFIG_INVALID"
        status = error.status if isinstance(error, DatabaseError) else 2
        if as_json:
            _json_response(
                "inspect",
                status,
                None,
                [
                    {"code": code, "severity": "error", "message": str(error)},
                ],
            )
        else:
            diagnostic(str(error))
        raise typer.Exit(status) from None

    if verbose:
        diagnostic("Completed schema inspection in a read-only transaction.")
    if as_json:
        issues: list[dict[str, object]] = [
            {
                "code": code,
                "severity": "warning",
                "message": "A schema feature is outside the supported generation subset.",
                "scope": {"table": item.id.model_dump(by_alias=True)},
            }
            for item in report.tables
            for code in item.issues
        ]
        _json_response(
            "inspect",
            0,
            {
                "schema": report.model_dump(mode="json", by_alias=True),
            },
            issues,
        )
    else:
        result("\n".join(inspection_lines(report)))


@app.command()
def plan(
    config: Annotated[Path, typer.Option("--config", help="Configuration path.")] = Path(
        "./seed.toml"
    ),
    schema: Annotated[str | None, typer.Option("--schema", help="Exact schema name.")] = None,
    table: Annotated[list[str] | None, typer.Option("--table", help="Select tables.")] = None,
    rows: Annotated[int | None, typer.Option("--rows", help="Override one table's count.")] = None,
    random_seed: Annotated[int | None, typer.Option("--random-seed")] = None,
    locale: Annotated[str | None, typer.Option("--locale")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit a JSON result.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """Plan generation from a read-only schema snapshot."""
    try:
        report = plan_database(
            config,
            schema=schema,
            filters=table or [],
            rows=rows,
            locale=locale,
            random_seed=random_seed,
        )
    except (ConfigError, DatabaseError) as error:
        code = error.code if isinstance(error, DatabaseError) else "CONFIG_INVALID"
        status = error.status if isinstance(error, DatabaseError) else 2
        if as_json:
            _json_response(
                "plan",
                status,
                None,
                [
                    {"code": code, "severity": "error", "message": str(error)},
                ],
            )
        else:
            diagnostic(str(error))
        raise typer.Exit(status) from None

    if verbose:
        diagnostic("Built the plan from a read-only schema snapshot.")
    if as_json:
        _json_response(
            "plan",
            0 if report.executable else 4,
            {
                "plan": report.model_dump(mode="json", by_alias=True),
            },
            plan_issues(report),
        )
    else:
        result("\n".join(plan_lines(report)))
    if not report.executable:
        raise typer.Exit(4)


def _json_response(
    command: str,
    status: int,
    data: dict[str, object] | None,
    issues: list[dict[str, object]],
) -> None:
    typer.echo(
        json.dumps(
            {
                "version": 1,
                "command": command,
                "ok": status == 0,
                "data": data,
                "issues": issues,
            }
        )
    )


def _render_issue(issue: dict[str, object]) -> None:
    scope = " · " + json.dumps(issue["scope"]) if "scope" in issue else ""
    diagnostic(f"{issue['code']} · {issue['message']}{scope}")


@app.command()
def validate(
    config: Annotated[Path, typer.Option("--config", help="Configuration path.")] = Path(
        "./seed.toml"
    ),
    schema: Annotated[str | None, typer.Option("--schema", help="Exact schema name.")] = None,
    table: Annotated[list[str] | None, typer.Option("--table", help="Select tables.")] = None,
    rows: Annotated[int | None, typer.Option("--rows", help="Override one table's count.")] = None,
    random_seed: Annotated[int | None, typer.Option("--random-seed")] = None,
    locale: Annotated[str | None, typer.Option("--locale")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit a JSON result.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
    dataset: Annotated[bool, typer.Option("--dataset", help="Validate all offline rows.")] = False,
) -> None:
    """Validate configuration, schema compatibility, and optional offline rows."""
    report = validate_request(
        PlanRequest(config, schema, table or [], rows, locale, random_seed),
        dataset=dataset,
    )
    if verbose:
        diagnostic("Completed staged validation.")
    if as_json:
        _json_response("validate", report.status, report.payload(), report.issues())
    else:
        for name, stage in report.stages().items():
            count = (
                f" · {stage.rows_checked} rows checked" if stage.rows_checked is not None else ""
            )
            result(f"{name} · {stage.status}{count}")
        for issue in report.issues():
            _render_issue(issue)
    if report.status:
        raise typer.Exit(report.status)


@app.command()
def preview(
    config: Annotated[Path, typer.Option("--config", help="Configuration path.")] = Path(
        "./seed.toml"
    ),
    schema: Annotated[str | None, typer.Option("--schema", help="Exact schema name.")] = None,
    table: Annotated[list[str] | None, typer.Option("--table", help="Select tables.")] = None,
    rows: Annotated[int | None, typer.Option("--rows", help="Override one table's count.")] = None,
    random_seed: Annotated[int | None, typer.Option("--random-seed")] = None,
    locale: Annotated[str | None, typer.Option("--locale")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit a JSON result.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
    limit: Annotated[int, typer.Option("--limit", help="Rows to show per requested table.")] = 5,
) -> None:
    """Show an offline sample from a read-only schema snapshot."""
    report = preview_request(
        PlanRequest(config, schema, table or [], rows, locale, random_seed), limit
    )
    if verbose:
        diagnostic("Completed offline preview.")
    if as_json:
        _json_response("preview", report.status, report.payload(), list(report.issues))
    else:
        lines = plan_lines(report.plan) if report.plan is not None else []
        for sample in report.tables:
            name = json.dumps(sample.table.table)
            lines.append(f"{name} · {len(sample.rows)} sampled rows")
            lines.append("  " + " | ".join(json.dumps(column.name) for column in sample.columns))
            lines.extend("  " + json.dumps(row) for row in sample.rows)
        if lines:
            result("\n".join(lines))
        if report.status:
            for issue in report.issues:
                _render_issue(issue)
    if report.status:
        raise typer.Exit(report.status)


def main() -> int:
    """Run the installed CLI and keep parser diagnostics free of arguments."""
    try:
        status = app(standalone_mode=False)
    except UsageError:
        diagnostic("Invalid command or options. Run seed --help for usage.")
        return 2
    return status if isinstance(status, int) else 0
