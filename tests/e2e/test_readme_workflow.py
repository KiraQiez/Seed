"""Exercise the beginner guide with a disposable database."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest
from conftest import PostgresFixture


def _guided_init(seed: Path, directory: Path, env: dict[str, str]) -> None:
    if sys.platform == "win32":
        pytest.skip("This terminal fixture uses a POSIX pseudoterminal")
    master, terminal = os.openpty()
    try:
        with subprocess.Popen(
            [str(seed), "init", "--interactive"],
            cwd=directory,
            env=env,
            stdin=terminal,
            stderr=terminal,
            stdout=subprocess.PIPE,
            encoding="utf-8",
        ) as process:
            os.write(master, b"\ncustomers\n\n\n")
            try:
                output, _ = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
            assert process.returncode == 0, output
            assert "Next: seed preview --limit 3" in output
    finally:
        os.close(master)
        os.close(terminal)


@pytest.mark.parametrize("setup", ["manual", "guided"])
def test_guide_walkthrough(postgres: PostgresFixture, tmp_path: Path, setup: str) -> None:
    database = f"seed_guide_{setup}"
    postgres.sql(f"CREATE DATABASE {database}")
    target = replace(postgres, database=database)
    target.sql("""
        CREATE TABLE public.customers (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            email varchar(160) NOT NULL
        )
    """)
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("PG")}
    env.update(DATABASE_URL=target.url, PYTHONIOENCODING="utf-8")
    seed = Path(sys.executable).with_name("seed.exe" if os.name == "nt" else "seed")

    def run(*args: str) -> str:
        process = subprocess.run(
            [str(seed), *args],
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            env=env,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        assert postgres.env["SEED_FIXTURE_PASSWORD"] not in process.stdout + process.stderr
        return process.stdout

    start = monotonic()
    config = tmp_path / "seed.toml"
    if setup == "guided":
        _guided_init(seed, tmp_path, env)
    else:
        run("init")
        with config.open("a", encoding="utf-8") as stream:
            stream.write("""
[tables.customers]
rows = 10
""")
    assert "10 planned rows" in run("plan")
    assert "3 of 10 rows" in run("preview", "--limit", "3")
    assert "Validation passed" in run("validate", "--dataset")
    assert "Exported 10 rows as JSON" in run("export", "--format", "json")
    assert target.sql("SELECT count(*) FROM public.customers") == "0"

    with config.open("a", encoding="utf-8") as stream:
        stream.write(f"""
[safety]
environment = "test"
[safety.target]
host = "127.0.0.1"
port = {target.port}
database = "{target.database}"
schema = "public"
""")
    assert "Dry-run passed. No rows written." in run("apply", "--dry-run")
    assert target.sql("SELECT count(*) FROM public.customers") == "0"
    assert "Committed 10 rows" in run("apply", "--yes")
    elapsed = monotonic() - start
    assert elapsed < 600
    assert target.sql("SELECT count(*) FROM public.customers") == "10"
    assert (tmp_path / "seed-export" / "manifest.json").is_file()
    print(f"Guide walkthrough ({setup}) elapsed {elapsed:.2f} seconds")
