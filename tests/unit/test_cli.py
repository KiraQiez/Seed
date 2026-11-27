"""Tests for the console entry point."""

import subprocess
import sys


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
    assert "--version" in completed.stdout
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
