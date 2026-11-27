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
from seed.initialize import initialize_config

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
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "version": 1,
                        "command": "init",
                        "ok": False,
                        "data": None,
                        "issues": [{"code": code, "severity": "error", "message": str(error)}],
                    }
                )
            )
        else:
            diagnostic(str(error))
        raise typer.Exit(2 if isinstance(error, ConfigError) else 6) from None

    if verbose:
        diagnostic("Created a starter configuration." if created else "Existing file preserved.")
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "version": 1,
                    "command": "init",
                    "ok": True,
                    "data": {"path": str(config), "created": created},
                    "issues": [],
                }
            )
        )
    else:
        result("Created seed configuration." if created else "Seed configuration already exists.")


def main() -> int:
    """Run the installed CLI and keep parser diagnostics free of arguments."""
    try:
        status = app(standalone_mode=False)
    except UsageError:
        diagnostic("Invalid command or options. Run seed --help for usage.")
        return 2
    return status if isinstance(status, int) else 0
