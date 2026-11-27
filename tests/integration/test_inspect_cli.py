"""Read-only inspection through the console entry point."""

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import PostgresFixture


def _inspect(
    config: Path,
    url: str,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    command = Path(sys.executable).with_name("seed.exe" if os.name == "nt" else "seed")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(SEED_TEST_URL=url, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [str(command), "inspect", "--config", str(config), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
        timeout=30,
    )


def _config(path: Path) -> Path:
    config = path / "seed.toml"
    config.write_text('version = 1\n[database]\nurl_env = "SEED_TEST_URL"\n', encoding="utf-8")
    return config


def test_inspect_reports_and_filters_without_database_changes(
    postgres: PostgresFixture,
    tmp_path: Path,
) -> None:
    postgres.sql("""
        CREATE SCHEMA "Cli.Scope";
        CREATE TABLE "Cli.Scope"."Parent.Items" (id integer PRIMARY KEY);
        CREATE TABLE "Cli.Scope"."Child.Items" (
            parent_id integer REFERENCES "Cli.Scope"."Parent.Items" (id),
            note text DEFAULT 'private-example',
            score integer CHECK (abs(score) > 1)
        );
        CREATE SEQUENCE "Cli.Scope".inspection_sequence;
        INSERT INTO "Cli.Scope"."Parent.Items" VALUES (12);
        INSERT INTO "Cli.Scope"."Child.Items" (parent_id, score) VALUES (12, 2);
    """)
    state_query = """
        SELECT (SELECT count(*) FROM "Cli.Scope"."Child.Items"),
               (SELECT count(*) FROM "Cli.Scope"."Parent.Items"),
               last_value, is_called
        FROM "Cli.Scope".inspection_sequence
    """
    before = postgres.sql(state_query)
    config = _config(tmp_path)
    full = _inspect(config, postgres.url, "--schema", "Cli.Scope", "--json")
    assert full.returncode == 0, full.stderr
    full_schema = json.loads(full.stdout)["data"]["schema"]
    assert len(full_schema["tables"]) == 2

    filtered = _inspect(
        config,
        postgres.url,
        "--schema",
        "Cli.Scope",
        "--table",
        '"Cli.Scope"."Child.Items"',
        "--json",
        "--verbose",
    )
    assert filtered.returncode == 0, filtered.stderr
    assert "read-only" in filtered.stderr
    payload = json.loads(filtered.stdout)
    schema = payload["data"]["schema"]
    assert schema["fingerprint"] == full_schema["fingerprint"]
    (child,) = schema["tables"]
    assert child["id"] == {"schema": "Cli.Scope", "table": "Child.Items"}
    assert child["foreign_keys"][0]["parent"]["table"] == "Parent.Items"
    assert payload["issues"][0]["code"] == "UNSUPPORTED_CHECK"
    assert "private-example" not in filtered.stdout
    assert "abs(score)" not in filtered.stdout

    human = _inspect(config, postgres.url, "--schema", "Cli.Scope")
    assert human.returncode == 0
    assert "Foreign key" in human.stdout
    assert "Detected only" in human.stdout
    assert "private-example" not in human.stdout
    assert postgres.sql(state_query) == before


def test_inspect_error_codes_and_redaction(postgres: PostgresFixture, tmp_path: Path) -> None:
    config = _config(tmp_path)
    without_schema = _inspect(config, postgres.url, "--schema", "not_present", "--json")
    assert without_schema.returncode == 4
    assert json.loads(without_schema.stdout)["issues"][0]["code"] == "SCHEMA_UNAVAILABLE"

    before, after = postgres.url.split("@", 1)
    bad_url = before.rsplit(":", 1)[0] + ":private-password@" + after
    for mode in ((), ("--json",)):
        failed = _inspect(config, bad_url, *mode)
        assert failed.returncode == 3
        assert "private-password" not in failed.stdout + failed.stderr
        assert "seed_fixture" not in failed.stdout + failed.stderr
