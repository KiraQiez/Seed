"""Tests for the console entry point."""

import subprocess
import sys
from json import loads
from pathlib import Path

import pytest
from rich.text import Text
from typer.testing import CliRunner

from seed import cli


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "from seed.cli import main; raise SystemExit(main())", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_help() -> None:
    completed = run_cli("--help")
    assert completed.returncode == 0
    assert "--version" in Text.from_ansi(completed.stdout).plain
    assert completed.stderr == ""


def test_narrow_help_identifies_the_first_step(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("GITHUB_ACTIONS", "FORCE_COLOR", "PY_COLORS"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("COLUMNS", "48")
    monkeypatch.setenv("NO_COLOR", "1")
    completed = run_cli("--help")
    assert completed.returncode == 0
    assert "Setup" in completed.stdout and "Review data" in completed.stdout
    assert "Save data" in completed.stdout and "seed init --interactive" in completed.stdout
    assert "\x1b[" not in completed.stdout
    assert completed.stderr == ""


def test_version() -> None:
    completed = run_cli("--version")
    assert completed.returncode == 0
    assert completed.stdout == "0.1.0\n"
    assert completed.stderr == ""


def test_unrecognized_input_uses_redacted_stderr() -> None:
    completed = run_cli("--private-value")
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Invalid command or options" in completed.stderr
    assert "private-value" not in completed.stderr


def test_init_json() -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        for created in (True, False):
            completed = run_cli("init", "--config", f"{directory}/seed.toml", "--json", "--verbose")
            assert completed.returncode == 0
            assert loads(completed.stdout)["data"]["created"] is created
            assert completed.stderr

        refused = run_cli("init", "--config", directory, "--json")
        assert refused.returncode == 6
        assert loads(refused.stdout)["issues"][0]["code"] == "INIT_FAILED"


def test_guided_setup_requires_terminal_and_rejects_json(tmp_path: Path) -> None:
    target = tmp_path / "seed.toml"
    command = ("init", "--interactive", "--config", str(target))
    nonterminal = run_cli(*command)
    assert nonterminal.returncode == 2
    assert "Open a terminal" in nonterminal.stderr
    invalid = run_cli(*command, "--json")
    assert invalid.returncode == 2
    assert loads(invalid.stdout)["issues"][0]["code"] == "CONFIG_INVALID"
    assert invalid.stderr == ""
    assert not target.exists()


@pytest.mark.parametrize(("error", "status"), [(EOFError, 5), (KeyboardInterrupt, 130)])
def test_guided_setup_cancels_without_creating_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException], status: int
) -> None:
    def cancel() -> str:
        raise error

    monkeypatch.setattr(cli, "_guided_setup", cancel)
    target = tmp_path / "seed.toml"
    result = CliRunner().invoke(cli.app, ["init", "--interactive", "--config", str(target)])
    assert result.exit_code == status
    assert "Setup cancelled" in result.stderr
    assert not target.exists()
