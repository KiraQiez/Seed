"""End-to-end safety and results through the installed Seed console script."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import PostgresFixture


def _config(path: Path, postgres: PostgresFixture, schema: str, *, append: bool = False) -> str:
    content = f"""
version=1
[database]
url_env="SEED_TEST_URL"
schema="{schema}"
[generation]
batch_size=2
default_rows=3
null_rate=0
[safety]
environment="test"
allow_existing_data={str(append).lower()}
[safety.target]
host="127.0.0.1"
port={postgres.port}
database="{postgres.database}"
schema="{schema}"
"""
    path.write_text(content, encoding="utf-8")
    return content


def _environment(postgres: PostgresFixture) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("PG")}
    env.update(SEED_TEST_URL=postgres.url, PYTHONIOENCODING="utf-8")
    return env


def _command(path: Path, *args: str) -> list[str]:
    script = Path(sys.executable).with_name("seed.exe" if os.name == "nt" else "seed")
    return [str(script), "apply", "--config", str(path), "--json", *args]


def _run(path: Path, postgres: PostgresFixture, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _command(path, *args),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        env=_environment(postgres),
        timeout=30,
        check=False,
    )


def test_apply_dry_run_refusal_commit_and_opted_in_append(
    postgres: PostgresFixture,
    tmp_path: Path,
) -> None:
    postgres.sql("""
        CREATE SCHEMA apply_cli;
        CREATE TABLE apply_cli.parent (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
        CREATE TABLE apply_cli.child (parent_id bigint NOT NULL REFERENCES apply_cli.parent(id));
    """)
    query = "SELECT last_value, is_called FROM apply_cli.parent_id_seq"
    before = postgres.sql(query)
    path = tmp_path / "seed.toml"
    contents = _config(path, postgres, "apply_cli")

    dry = _run(path, postgres, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    report = json.loads(dry.stdout)
    assert report["command"] == "apply" and report["version"] == 1 and report["ok"]
    assert report["data"]["dry_run"] and report["data"]["insertion"] is None
    assert report["data"]["plan"]["total_rows"] == 6
    assert "6 planned rows" in dry.stderr and "127.0.0.1" in dry.stderr
    assert postgres.sql(query) == before

    refused = _run(path, postgres)
    assert refused.returncode == 5
    report = json.loads(refused.stdout)
    assert report["data"]["insertion"]["outcome"] == "not_started"
    assert report["issues"][-1]["code"] == "CONFIRMATION_REQUIRED"
    assert "Apply the planned rows?" not in refused.stderr
    assert postgres.sql(query) == before
    invalid = _run(path, postgres, "--dry-run", "--yes")
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["data"]["insertion"] is None

    path.write_text(contents.replace(f"port={postgres.port}", "port=1"), encoding="utf-8")
    mismatch = _run(path, postgres, "--yes")
    assert mismatch.returncode == 5
    assert json.loads(mismatch.stdout)["issues"][-1]["code"] == "TARGET_MISMATCH"
    path.write_text(contents, encoding="utf-8")
    first = _run(path, postgres, "--yes")
    assert first.returncode == 0, first.stderr
    insertion = json.loads(first.stdout)["data"]["insertion"]
    assert insertion["outcome"] == "committed"
    assert [(count["table"]["table"], count["rows"]) for count in insertion["counts"]] == [
        ("parent", 3),
        ("child", 3),
    ]
    assert postgres.env["SEED_FIXTURE_PASSWORD"] not in first.stdout + first.stderr

    nonempty = _run(path, postgres, "--yes")
    assert nonempty.returncode == 5
    assert json.loads(nonempty.stdout)["issues"][-1]["code"] == "TARGET_NOT_EMPTY"
    assert postgres.sql("SELECT count(*) FROM apply_cli.child") == "3"
    _config(path, postgres, "apply_cli", append=True)
    second = _run(path, postgres, "--yes")
    assert second.returncode == 0, second.stderr
    assert (
        postgres.sql("""
        SELECT count(*) FROM apply_cli.child JOIN apply_cli.parent
        ON apply_cli.child.parent_id = apply_cli.parent.id
    """)
        == "6"
    )


@pytest.mark.parametrize("reply", [b"n\n", b"\x04"])
def test_actual_terminal_decline_and_eof(
    postgres: PostgresFixture,
    tmp_path: Path,
    reply: bytes,
) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX terminal test")
    postgres.sql("""
        CREATE SCHEMA IF NOT EXISTS apply_terminal;
        CREATE TABLE IF NOT EXISTS apply_terminal.items (id integer);
    """)
    path = tmp_path / "seed.toml"
    _config(path, postgres, "apply_terminal")
    master, terminal = os.openpty()
    try:
        with subprocess.Popen(
            _command(path),
            stdin=terminal,
            stderr=terminal,
            stdout=subprocess.PIPE,
            encoding="utf-8",
            env=_environment(postgres),
        ) as process:
            os.write(master, reply)
            try:
                output, _ = process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
            assert process.returncode == 5
    finally:
        os.close(terminal)
        os.close(master)
    outcome = json.loads(output)
    assert outcome["issues"][-1]["code"] == "CANCELLED"
    assert outcome["data"]["insertion"] == {"outcome": "not_started"}
    assert postgres.sql("SELECT count(*) FROM apply_terminal.items") == "0"


def test_cli_rollback_never_reports_rolled_back_counts(
    postgres: PostgresFixture,
    tmp_path: Path,
) -> None:
    postgres.sql("""
        CREATE SCHEMA apply_failure_cli;
        CREATE TABLE apply_failure_cli.items (
            id smallint GENERATED ALWAYS AS IDENTITY (MAXVALUE 2) PRIMARY KEY
        );
    """)
    path = tmp_path / "seed.toml"
    _config(path, postgres, "apply_failure_cli")
    failure = _run(path, postgres, "--yes")
    assert failure.returncode == 6
    payload = json.loads(failure.stdout)
    assert payload["data"]["insertion"] == {"outcome": "rolled_back"}
    assert payload["issues"][-1]["code"] == "INSERT_FAILED"
    assert postgres.env["SEED_FIXTURE_PASSWORD"] not in failure.stdout + failure.stderr
    assert postgres.sql("SELECT count(*) FROM apply_failure_cli.items") == "0"
