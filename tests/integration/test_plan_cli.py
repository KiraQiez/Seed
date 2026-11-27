"""Read-only planning through the installed command."""

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import PostgresFixture


def run_plan(
    config: Path,
    postgres: PostgresFixture,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    executable = Path(sys.executable).with_name("seed.exe" if os.name == "nt" else "seed")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(SEED_TEST_URL=postgres.url, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [str(executable), "plan", "--config", str(config), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
        timeout=30,
    )


def test_plan_cli_preserves_database_and_distinguishes_blocked_reports(
    postgres: PostgresFixture,
    tmp_path: Path,
) -> None:
    postgres.sql("""
        CREATE SCHEMA "Seed.Plan";
        CREATE TABLE "Seed.Plan"."Parent.Row" (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
        CREATE TABLE "Seed.Plan".child (
            id integer PRIMARY KEY, parent_id bigint REFERENCES "Seed.Plan"."Parent.Row"(id)
        );
        CREATE TABLE "Seed.Plan".broken (id integer CHECK (abs(id) > 2));
        INSERT INTO "Seed.Plan"."Parent.Row" DEFAULT VALUES;
        INSERT INTO "Seed.Plan".child VALUES (1, 1);
    """)
    state_query = """
        SELECT (SELECT count(*) FROM "Seed.Plan".child), last_value, is_called
        FROM "Seed.Plan"."Parent.Row_id_seq"
    """
    before = postgres.sql(state_query)
    config = tmp_path / "seed.toml"
    config.write_text(
        'version=1\n[database]\nurl_env="SEED_TEST_URL"\n[tables."Parent.Row"]\nrows=3\n',
        encoding="utf-8",
    )
    options = ("--schema", "Seed.Plan", "--table", "child", "--rows", "2")
    completed = run_plan(
        config, postgres, *options, "--random-seed", "12", "--locale", "en_GB", "--json"
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    report = payload["data"]["plan"]
    assert payload["ok"] and report["total_rows"] == 5
    assert report["settings"]["random_seed"] == 12
    assert report["settings"]["locale"] == "en_GB"
    parent, child = report["tables"]
    assert parent["id"]["table"] == "Parent.Row" and not parent["requested"]
    assert child["id"]["table"] == "child" and child["requested"]
    assert parent["bindings"]["live"][0]["source"] == "server_identity"
    assert parent["bindings"]["offline"][0]["source"] == "explicit_identity"

    terminal = run_plan(config, postgres, *options)
    assert terminal.returncode == 0 and "5 planned rows" in terminal.stdout
    blocked = run_plan(config, postgres, "--schema", "Seed.Plan", "--table", "broken", "--json")
    assert blocked.returncode == 4
    error = json.loads(blocked.stdout)
    assert not error["ok"] and error["data"]["plan"]["total_rows"] == 100
    assert {issue["scope"]["mode"] for issue in error["issues"]} == {"live", "offline"}
    assert {issue["code"] for issue in error["issues"]} == {"UNSUPPORTED_CHECK"}
    invalid = run_plan(config, postgres, "--rows", "1", "--json")
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["issues"][0]["code"] == "CONFIG_INVALID"
    assert postgres.sql(state_query) == before
