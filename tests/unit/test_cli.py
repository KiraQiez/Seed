"""Tests for the console entry point."""

import subprocess
import sys

from rich.text import Text


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
    from json import loads
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
