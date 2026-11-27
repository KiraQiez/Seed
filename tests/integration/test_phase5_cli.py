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
