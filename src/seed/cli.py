"""Terminal entry point for Seed."""

import typer
from rich.console import Console
from rich.text import Text
from typer._click.exceptions import UsageError

from seed import __version__

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
    version: bool = typer.Option(False, "--version", is_eager=True, help="Show the package version."),
) -> None:
    """Work with Seed configurations and datasets."""
    if version:
        result(__version__)
        raise typer.Exit()


def main() -> int:
    """Run the installed CLI and keep parser diagnostics free of arguments."""
    try:
        status = app(standalone_mode=False)
    except UsageError:
        diagnostic("Invalid command or options. Run seed --help for usage.")
        return 2
    return status if isinstance(status, int) else 0
