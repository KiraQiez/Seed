"""Terminal entry point for Seed."""

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console, RenderableType
from rich.text import Text
from typer._click.exceptions import UsageError

from seed import __version__
from seed.config import ConfigError
from seed.planning.plan import PlanRequest, plan_database
from seed.postgres.connection import DatabaseError
from seed.postgres.inspection import inspect_database
from seed.reporting.inspection import inspection_lines, safe_text
from seed.reporting.plan import plan_issues, plan_lines
from seed.reporting.terminal import (
    apply_summary,
    export_summary,
    inspection_summary,
    plan_summary,
    preview_summary,
    validation_summary,
)
from seed.workflows.apply import run_apply
from seed.workflows.export import ExportFormat, run_export
from seed.workflows.initialize import guided_starter, initialize_config
from seed.workflows.preview import preview as preview_request
from seed.workflows.validate import validate as validate_request

ConfigOption = Annotated[
    Path,
    typer.Option(
        "--config", rich_help_panel="Connection and selection", help="Configuration path."
    ),
]
SchemaOption = Annotated[
    str | None,
    typer.Option("--schema", rich_help_panel="Connection and selection", help="Exact schema name."),
]
TableOption = Annotated[
    list[str] | None,
    typer.Option("--table", rich_help_panel="Connection and selection", help="Select tables."),
]
RowsOption = Annotated[
    int | None,
    typer.Option("--rows", rich_help_panel="Generation", help="Override one table's count."),
]
SeedOption = Annotated[
    int | None,
    typer.Option(
        "--random-seed", rich_help_panel="Generation", help="Use a seed to repeat generation."
    ),
]
LocaleOption = Annotated[
    str | None,
    typer.Option("--locale", rich_help_panel="Generation", help="Locale for generated values."),
]
JsonOption = Annotated[
    bool, typer.Option("--json", rich_help_panel="Output", help="Emit a JSON result.")
]
VerboseOption = Annotated[
    bool,
    typer.Option("--verbose", rich_help_panel="Output", help="Show additional diagnostics."),
]

app = typer.Typer(
    help="Generate test data for PostgreSQL.",
    epilog="First run: seed init --interactive, set DATABASE_URL, then run seed preview.",
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def result(message: RenderableType) -> None:
    """Write a result to stdout."""
    Console().print(Text(message) if isinstance(message, str) else message)


def diagnostic(message: str) -> None:
    """Write a diagnostic to stderr."""
    Console(stderr=True).print(Text(message))


@app.callback()
def root(
    version: bool = typer.Option(
        False, "--version", is_eager=True, help="Show the package version."
    ),
) -> None:
    """Generate test data for PostgreSQL."""
    if version:
        result(__version__)
        raise typer.Exit()


@app.command(rich_help_panel="Setup")
def init(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            rich_help_panel="Connection and selection",
            help="Starter configuration path.",
        ),
    ] = Path("./seed.toml"),
    as_json: JsonOption = False,
    verbose: VerboseOption = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            rich_help_panel="Setup",
            help="Choose tables and row counts with prompts.",
        ),
    ] = False,
) -> None:
    """Create a starter configuration."""
    try:
        if interactive and as_json:
            raise ConfigError("Use --interactive or --json separately.")
        created = initialize_config(config, starter=_guided_setup if interactive else None)
    except (EOFError, KeyboardInterrupt) as error:
        diagnostic("Setup cancelled.")
        raise typer.Exit(5 if isinstance(error, EOFError) else 130) from None
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
            _render_issue({"code": code, "severity": "error", "message": str(error)})
        raise typer.Exit(status) from None

    if verbose:
        diagnostic("Created a starter configuration." if created else "Existing file preserved.")
    if as_json:
        _json_response("init", 0, {"path": str(config), "created": created}, [])
    else:
        result("Created seed configuration." if created else "Seed configuration already exists.")
        if created and interactive:
            result("Set DATABASE_URL to your development or test database connection URL.")
            result("Next: seed preview --limit 3")
            if config != Path("seed.toml"):
                result("Use the same --config path for preview.")


def _guided_setup() -> str:
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        raise ConfigError("Open a terminal to use guided setup, or run seed init.")

    def prompt(message: str) -> str:
        sys.stderr.write(message)
        sys.stderr.flush()
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")

    return guided_starter(prompt, diagnostic)


@app.command(rich_help_panel="Review data")
def inspect(
    config: ConfigOption = Path("./seed.toml"),
    schema: SchemaOption = None,
    table: Annotated[
        list[str] | None,
        typer.Option(
            "--table", rich_help_panel="Connection and selection", help="Limit displayed tables."
        ),
    ] = None,
    as_json: JsonOption = False,
    verbose: VerboseOption = False,
) -> None:
    """See the tables and columns in your database."""
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
            _render_issue({"code": code, "severity": "error", "message": str(error)})
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
    elif table:
        result("\n".join(inspection_lines(report)))
    else:
        result(inspection_summary(report))
        if verbose:
            diagnostic("\n".join(inspection_lines(report)))


@app.command(rich_help_panel="Review data")
def plan(
    config: ConfigOption = Path("./seed.toml"),
    schema: SchemaOption = None,
    table: TableOption = None,
    rows: RowsOption = None,
    random_seed: SeedOption = None,
    locale: LocaleOption = None,
    as_json: JsonOption = False,
    verbose: VerboseOption = False,
) -> None:
    """See which tables Seed will fill and how many rows it will generate."""
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
            _render_issue({"code": code, "severity": "error", "message": str(error)})
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
        result(plan_summary(report))
        for issue in plan_issues(report):
            _render_issue(issue)
        if verbose:
            diagnostic("\n".join(plan_lines(report)))
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


_HINTS = {
    "CONFIG_INVALID": "Check seed.toml and the environment variable named in database.url_env.",
    "CONNECTION_FAILED": "Check the connection URL and confirm that PostgreSQL is running.",
    "CONNECTION_TIMEOUT": "Check that PostgreSQL is reachable from this terminal.",
    "TARGET_REQUIRED": "Set the target in seed.toml, then run seed apply --dry-run.",
    "TARGET_MISMATCH": "Compare the configured target with your database URL and selected schema.",
    "TARGET_NOT_EMPTY": "Use an empty test table, or save the generated rows with seed export.",
    "OUTPUT_EXISTS": "Choose a fresh directory with --output.",
    "CONFIRMATION_REQUIRED": "Run seed apply from a terminal to review and confirm the write.",
}


def _render_issue(issue: dict[str, object]) -> None:
    code = str(issue["code"])
    severity = "Warning" if issue["severity"] == "warning" else "Error"
    scope = " · " + json.dumps(issue["scope"]) if "scope" in issue else ""
    diagnostic(safe_text(f"{severity} [{code}] {issue['message']}{scope}"))
    if hint := _HINTS.get(code):
        diagnostic(hint)


@app.command(rich_help_panel="Review data")
def validate(
    config: ConfigOption = Path("./seed.toml"),
    schema: SchemaOption = None,
    table: TableOption = None,
    rows: RowsOption = None,
    random_seed: SeedOption = None,
    locale: LocaleOption = None,
    as_json: JsonOption = False,
    verbose: VerboseOption = False,
    dataset: Annotated[
        bool, typer.Option("--dataset", rich_help_panel="Checks", help="Validate all offline rows.")
    ] = False,
) -> None:
    """Check your setup, plan, and optionally all generated rows."""
    report = validate_request(
        PlanRequest(config, schema, table or [], rows, locale, random_seed),
        dataset=dataset,
    )
    if verbose:
        diagnostic("Completed staged validation.")
    if as_json:
        _json_response("validate", report.status, report.payload(), report.issues())
    else:
        result(validation_summary(report))
        for issue in report.issues():
            _render_issue(issue)
    if report.status:
        raise typer.Exit(report.status)


@app.command(rich_help_panel="Review data")
def preview(
    config: ConfigOption = Path("./seed.toml"),
    schema: SchemaOption = None,
    table: TableOption = None,
    rows: RowsOption = None,
    random_seed: SeedOption = None,
    locale: LocaleOption = None,
    as_json: JsonOption = False,
    verbose: VerboseOption = False,
    limit: Annotated[
        int,
        typer.Option("--limit", rich_help_panel="Output", help="Rows to show per requested table."),
    ] = 5,
) -> None:
    """Preview sample rows without writing to the database."""
    report = preview_request(
        PlanRequest(config, schema, table or [], rows, locale, random_seed), limit
    )
    if verbose:
        diagnostic("Completed offline preview.")
    if as_json:
        _json_response("preview", report.status, report.payload(), list(report.issues))
    else:
        if report.plan is not None:
            result(plan_summary(report.plan))
            planned_counts = {table.id: table.rows for table in report.plan.tables}
            console = Console()
            for sample in report.tables:
                console.print(preview_summary(sample, planned_counts[sample.table], console.width))
            if verbose:
                diagnostic("\n".join(plan_lines(report.plan)))
        for issue in report.issues:
            _render_issue(issue)
    if report.status:
        raise typer.Exit(report.status)


def _apply_prompt() -> str:
    sys.stderr.write("Apply the planned rows? [y/N] ")
    sys.stderr.flush()
    return sys.stdin.readline()


@app.command(rich_help_panel="Save data")
def apply(
    config: ConfigOption = Path("./seed.toml"),
    schema: SchemaOption = None,
    table: TableOption = None,
    rows: RowsOption = None,
    random_seed: SeedOption = None,
    locale: LocaleOption = None,
    as_json: JsonOption = False,
    verbose: VerboseOption = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            rich_help_panel="Write safety",
            help="Check the target and plan without writing rows.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            rich_help_panel="Write safety",
            help="Approve the write without an interactive prompt.",
        ),
    ] = False,
) -> None:
    """Insert rows into an explicitly configured development or test database."""
    report = run_apply(
        PlanRequest(config, schema, table or [], rows, locale, random_seed),
        yes=yes,
        dry_run=dry_run,
        interactive=sys.stdin.isatty() and sys.stderr.isatty(),
        prompt=_apply_prompt,
        show_target=diagnostic,
    )
    if verbose:
        diagnostic("Completed apply workflow.")
    if as_json:
        _json_response("apply", report.status, report.payload(), report.issues)
    else:
        if not report.status:
            result(apply_summary(report))
        else:
            outcome = report.insertion.outcome if report.insertion else "not_started"
            diagnostic(
                {
                    "rolled_back": "Apply rolled back.",
                    "unknown": "The commit result is unknown.",
                }.get(outcome, "No rows written.")
            )
        for issue in report.issues:
            _render_issue(issue)
    if report.status:
        raise typer.Exit(report.status)


@app.command(rich_help_panel="Save data")
def export(
    format: Annotated[
        ExportFormat, typer.Option("--format", rich_help_panel="Output", help="Artifact format.")
    ],
    config: ConfigOption = Path("./seed.toml"),
    schema: SchemaOption = None,
    table: TableOption = None,
    rows: RowsOption = None,
    random_seed: SeedOption = None,
    locale: LocaleOption = None,
    as_json: JsonOption = False,
    verbose: VerboseOption = False,
    output: Annotated[
        Path, typer.Option("--output", rich_help_panel="Output", help="New export directory.")
    ] = Path("./seed-export"),
) -> None:
    """Save generated rows to SQL, CSV, or JSON files."""
    report = run_export(
        PlanRequest(config, schema, table or [], rows, locale, random_seed), format, output
    )
    if verbose and report.result is not None:
        diagnostic("Published the export manifest.")
    if as_json:
        data: dict[str, object] | None = (
            {"export": report.result.payload()} if report.result is not None else None
        )
        _json_response("export", report.status, data, list(report.issues))
    else:
        for issue in report.issues:
            _render_issue(issue)
        if report.result is not None:
            result(export_summary(report.result))
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
