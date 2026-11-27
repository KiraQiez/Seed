"""Validation and preview through the installed console entry point."""

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import PostgresFixture


def invoke(command: str, config: Path, url: str, *options: str) -> subprocess.CompletedProcess[str]:
    executable = Path(sys.executable).with_name("seed.exe" if os.name == "nt" else "seed")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(SEED_TEST_URL=url, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [str(executable), command, "--config", str(config), *options],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
        timeout=30,
    )


def test_validate_distinguishes_stage_status_counts_and_safe_errors(
    postgres: PostgresFixture,
    tmp_path: Path,
) -> None:
    postgres.sql("""
        CREATE SCHEMA validate_seed;
        CREATE TABLE validate_seed.items (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
        CREATE TABLE validate_seed.broken (id integer CHECK (abs(id) > 2));
        CREATE TABLE validate_seed.finite (code text NOT NULL UNIQUE);
        INSERT INTO validate_seed.items DEFAULT VALUES;
    """)
    query = """
        SELECT (SELECT count(*) FROM validate_seed.items), last_value, is_called
        FROM validate_seed.items_id_seq
    """
    before = postgres.sql(query)
    config = tmp_path / "seed.toml"
    config.write_text(
        'version=1\n[database]\nurl_env="SEED_TEST_URL"\nschema="validate_seed"\n'
        '[rules.finite.code]\ngenerator="constant"\nvalue="private-test-value"\n',
        encoding="utf-8",
    )

    def statuses(
        completed: subprocess.CompletedProcess[str],
        code: int,
        expected: tuple[str, ...],
    ) -> None:
        assert completed.returncode == code, completed.stderr
        payload = json.loads(completed.stdout)
        assert payload["ok"] is (code == 0)
        stages = payload["data"]
        assert tuple(stages[key]["status"] for key in ("config", "plan", "dataset")) == expected
        assert "private-test-value" not in completed.stdout + completed.stderr

    statuses(
        invoke("validate", config, postgres.url, "--table", "items", "--json"),
        0,
        ("passed", "passed", "skipped"),
    )
    complete = invoke(
        "validate",
        config,
        postgres.url,
        "--table",
        "items",
        "--rows",
        "6",
        "--dataset",
        "--json",
        "--verbose",
    )
    statuses(complete, 0, ("passed", "passed", "passed"))
    assert json.loads(complete.stdout)["data"]["dataset"]["rows_checked"] == 6
    assert "Completed staged validation" in complete.stderr
    statuses(
        invoke("validate", config, postgres.url, "--rows", "2", "--dataset", "--json"),
        2,
        ("failed", "skipped", "skipped"),
    )
    bad_url = (
        postgres.url.split(":", 2)[0]
        + "://seed_fixture:private-test-password@"
        + (postgres.url.split("@", 1)[1])
    )
    rejected = invoke("validate", config, bad_url, "--table", "items", "--json")
    statuses(rejected, 3, ("passed", "failed", "skipped"))
    assert "private-test-password" not in rejected.stdout + rejected.stderr
    statuses(
        invoke("validate", config, postgres.url, "--table", "broken", "--dataset", "--json"),
        4,
        ("passed", "failed", "skipped"),
    )
    finite = invoke(
        "validate",
        config,
        postgres.url,
        "--table",
        "finite",
        "--rows",
        "2",
        "--dataset",
        "--json",
    )
    statuses(finite, 4, ("passed", "passed", "failed"))
    assert json.loads(finite.stdout)["issues"][0]["code"] == "DOMAIN_EXHAUSTED"
    assert postgres.sql(query) == before


def test_preview_samples_match_full_rows_and_preserve_composite_parent_pools(
    postgres: PostgresFixture,
    tmp_path: Path,
) -> None:
    from test_schema import snapshot

    from seed.config import load_config
    from seed.generation.engine import generate_batches
    from seed.planning.plan import build_plan
    from seed.reporting.dataset import dataset_columns, dataset_row

    postgres.sql("""
        CREATE SCHEMA preview_seed;
        CREATE TABLE preview_seed.parent (
            id bigint GENERATED ALWAYS AS IDENTITY,
            code text NOT NULL,
            PRIMARY KEY (id, code)
        );
        CREATE TABLE preview_seed.child (
            parent_id bigint NOT NULL, parent_code text NOT NULL,
            FOREIGN KEY (parent_id, parent_code) REFERENCES preview_seed.parent (id, code),
            amount numeric(6, 2) NOT NULL CHECK (amount > 3.00 AND amount < 3.02),
            computed numeric GENERATED ALWAYS AS (amount * 2) STORED
        );
        CREATE TABLE preview_seed.empty (id integer);
        CREATE TABLE preview_seed.blocked (id integer CHECK (abs(id) > 2));
    """)
    query = """
        SELECT (SELECT count(*) FROM preview_seed.child), last_value, is_called
        FROM preview_seed.parent_id_seq
    """
    before = postgres.sql(query)
    path = tmp_path / "seed.toml"
    path.write_text(
        'version=1\n[database]\nurl_env="SEED_TEST_URL"\nschema="preview_seed"\n'
        "[generation]\nnull_rate=0\n[tables.parent]\nrows=6\n[tables.child]\nrows=7\n"
        "[tables.empty]\nrows=0\n",
        encoding="utf-8",
    )
    opts = ("--limit", "2", "--json")
    actual = invoke("preview", path, postgres.url, *opts)
    assert actual.returncode == 0, actual.stderr
    assert actual.stdout == invoke("preview", path, postgres.url, *opts).stdout
    payload = json.loads(actual.stdout)
    output = {item["table"]["table"]: item for item in payload["data"]["tables"]}
    schema = snapshot(postgres, "preview_seed").schema
    config = load_config(path)
    plan = build_plan(config, schema, [])
    assert payload["data"]["plan"]["total_rows"] == plan.total_rows == 13
    metadata = {table.id: dataset_columns(table) for table in schema.tables}
    for batch in generate_batches(plan, schema, config):
        name = batch[0].table.table
        assert output[name]["rows"] == [
            list(dataset_row(record, metadata[record.table])) for record in batch[:2]
        ]
    assert output["empty"]["columns"] == [{"name": "id", "type": "integer"}]
    assert output["empty"]["rows"] == []
    assert all(row[-1] == "3.01" for row in output["child"]["rows"])
    assert output["parent"]["rows"][0][0] == "1"
    assert "computed" not in {column["name"] for column in output["child"]["columns"]}

    child_only = invoke("preview", path, postgres.url, *opts, "--table", "child", "--verbose")
    assert child_only.returncode == 0 and child_only.stderr
    assert json.loads(child_only.stdout)["data"]["tables"] == [output["child"]]

    blocked = invoke("preview", path, postgres.url, "--table", "blocked", "--json")
    assert blocked.returncode == 4
    assert json.loads(blocked.stdout)["data"]["tables"] == []
    unusable = invoke("preview", path, postgres.url, "--limit", "0", "--json")
    assert unusable.returncode == 2
    assert postgres.sql(query) == before


def test_live_only_plan_blocks_offline_consumers(
    postgres: PostgresFixture,
    tmp_path: Path,
) -> None:
    postgres.sql("""
        CREATE SCHEMA preview_live_only;
        CREATE TABLE preview_live_only.parent (id integer PRIMARY KEY);
        CREATE TABLE preview_live_only.child (
            parent_id integer NOT NULL REFERENCES preview_live_only.parent (id)
        );
    """)
    config = tmp_path / "seed.toml"
    config.write_text(
        'version=1\n[database]\nurl_env="SEED_TEST_URL"\nschema="preview_live_only"\n'
        "[tables.parent]\nrows=0\nreuse_existing=true\n[tables.child]\nrows=1\n",
        encoding="utf-8",
    )
    base = invoke("validate", config, postgres.url, "--json")
    assert base.returncode == 0
    assert json.loads(base.stdout)["data"]["dataset"]["status"] == "skipped"
    full = invoke("validate", config, postgres.url, "--dataset", "--json")
    assert full.returncode == 4
    stages = json.loads(full.stdout)["data"]
    assert stages["plan"]["status"] == "passed"
    assert stages["dataset"]["status"] == "failed"
    assert stages["dataset"]["rows_checked"] == 0
    assert stages["dataset"]["issues"][0]["code"] == "PLAN_BLOCKED"
    sample = invoke("preview", config, postgres.url, "--json")
    assert sample.returncode == 4
    assert json.loads(sample.stdout)["data"]["tables"] == []
