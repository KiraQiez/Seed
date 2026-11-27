"""Machine-readable envelopes never include raw input or diagnostics."""

import json
from pathlib import Path

import pytest
from test_cli import run_cli


@pytest.mark.parametrize("command", ["inspect", "plan", "validate", "preview"])
def test_config_errors_use_one_safe_json_envelope(command: str, tmp_path: Path) -> None:
    config = tmp_path / "seed.toml"
    config.write_text(
        'version = 1\n[database]\nurl_env = "postgresql://user:never-print@host/db"\n',
        encoding="utf-8",
    )
    completed = run_cli(command, "--config", str(config), "--json")
    assert completed.returncode == 2
    assert completed.stdout.count("\n") == 1
    assert completed.stderr == ""
    assert "never-print" not in completed.stdout
    payload = json.loads(completed.stdout)
    assert set(payload) == {"version", "command", "ok", "data", "issues"}
    assert payload["version"] == 1 and payload["command"] == command and not payload["ok"]
    assert payload["issues"][0]["code"] == "CONFIG_INVALID"
    if command == "validate":
        assert payload["data"]["config"]["status"] == "failed"
    else:
        assert payload["data"] is None


def test_init_json_keeps_verbose_diagnostics_separate(tmp_path: Path) -> None:
    path = tmp_path / "seed.toml"
    completed = run_cli("init", "--config", str(path), "--json", "--verbose")
    assert completed.returncode == 0
    assert "Created a starter configuration." in completed.stderr
    assert completed.stdout.count("\n") == 1
    assert json.loads(completed.stdout) == {
        "version": 1,
        "command": "init",
        "ok": True,
        "data": {"path": str(path), "created": True},
        "issues": [],
    }
