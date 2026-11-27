"""Exercise the README on a premigrated, disposable database."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from time import monotonic

from conftest import PostgresFixture


def test_readme_walkthrough(postgres: PostgresFixture, tmp_path: Path) -> None:
    postgres.sql("CREATE DATABASE seed_readme")
    target = replace(postgres, database="seed_readme")
    target.sql("""
        CREATE TABLE public.customers (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            email varchar(160) NOT NULL
        )
    """)
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("PG")}
    env.update(DATABASE_URL=target.url, PYTHONIOENCODING="utf-8")
    seed = Path(sys.executable).with_name("seed.exe" if os.name == "nt" else "seed")

    def run(*args: str) -> None:
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

    start = monotonic()
    run("init")
    config = tmp_path / "seed.toml"
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
    run("inspect")
    run("plan", "--table", "customers")
    run("preview", "--table", "customers", "--limit", "5")
    run("validate", "--table", "customers", "--dataset")
    run("export", "--table", "customers", "--format", "json")
    run("apply", "--table", "customers", "--dry-run")
    assert target.sql("SELECT count(*) FROM public.customers") == "0"
    run("apply", "--table", "customers", "--yes")
    elapsed = monotonic() - start
    assert elapsed < 600
    assert target.sql("SELECT count(*) FROM public.customers") == "100"
    assert (tmp_path / "seed-export" / "manifest.json").is_file()
    print(f"README walkthrough elapsed {elapsed:.2f} seconds")
