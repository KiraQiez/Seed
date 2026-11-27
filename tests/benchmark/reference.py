"""Measure the reference workflow inside the isolated Linux benchmark container."""

import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from psycopg import Connection, connect
from psycopg.sql import SQL, Identifier

_COUNTS = {
    "customers": 1000,
    "products": 500,
    "orders": 5000,
    "order_items": 15000,
    "payments": 5000,
}
_EDGES = (
    ("orders", "customer_id", "customers"),
    ("order_items", "order_id", "orders"),
    ("order_items", "product_id", "products"),
    ("payments", "order_id", "orders"),
)
_ROOT = Path(__file__).resolve().parents[2]
_SEED = Path(sys.executable).with_name("seed")


def _environment() -> dict[str, object]:
    cpu = Path("/sys/fs/cgroup/cpu.max").read_text().split()
    memory = int(Path("/sys/fs/cgroup/memory.max").read_text())
    assert int(cpu[0]) == 4 * int(cpu[1]) and (os.cpu_count() or 0) >= 4
    assert memory == 8 * 1024**3
    assert sys.version_info[:2] == (3, 12) and sys.platform == "linux"
    return {
        "linux": platform.release(),
        "architecture": platform.machine(),
        "cpu_quota": 4,
        "memory_bytes": memory,
        "python": platform.python_version(),
        "dependencies": {
            package: version(package)
            for package in ("Faker", "psycopg", "pydantic", "rich", "sqlalchemy", "typer")
        },
    }


def _config(path: Path, *, append: bool = False) -> None:
    path.write_text(
        f"""
version = 1
[database]
url_env = "SEED_BENCHMARK_URL"
schema = "ecommerce"
[generation]
random_seed = 42
locale = "en_US"
batch_size = 1000
[safety]
environment = "test"
allow_existing_data = {str(append).lower()}
[safety.target]
host = "127.0.0.1"
port = 5432
database = "seed_benchmark"
schema = "ecommerce"
"""
        + "".join(f"\n[tables.{table}]\nrows = {count}\n" for table, count in _COUNTS.items()),
        encoding="utf-8",
    )


def _timed(directory: Path, command: list[str], *options: str) -> dict[str, float | int]:
    timing = directory / "time.txt"
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env["SEED_APPEND_TIMING"] = str(directory / "append.json")
    process = subprocess.run(
        [
            "/usr/bin/time",
            "-f",
            "%e %M",
            "-o",
            str(timing),
            *command,
            *options,
            "--config",
            str(directory / "seed.toml"),
            "--json",
        ],
        env=env,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=180,
    )
    if process.returncode:
        issues = json.loads(process.stdout).get("issues", []) if process.stdout else []
        codes = ", ".join(issue["code"] for issue in issues)
        raise RuntimeError(f"Benchmark CLI failed with status {process.returncode}. {codes}")
    assert json.loads(process.stdout)["ok"]
    elapsed, peak = timing.read_text().split()
    return {"elapsed_seconds": float(elapsed), "peak_rss_kib": int(peak)}


def _verify_database(connection: Connection[Any], copies: int) -> None:
    for table, count in _COUNTS.items():
        name = Identifier("ecommerce", table)
        observed = connection.execute(SQL("SELECT count(*) FROM {}").format(name)).fetchone()
        assert observed == (copies * count,), table
        if copies == 0:
            state = connection.execute(
                SQL("SELECT last_value, is_called FROM {}").format(
                    Identifier("ecommerce", f"{table}_id_seq")
                )
            ).fetchone()
            assert state == (1, False), table
    for child, key, parent in _EDGES:
        sql = SQL(
            "SELECT count(*) FROM {} c LEFT JOIN {} p ON c.{} = p.id WHERE p.id IS NULL"
        ).format(Identifier("ecommerce", child), Identifier("ecommerce", parent), Identifier(key))
        assert connection.execute(sql).fetchone() == (0,)


def _verify_json(path: Path) -> None:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    data = json.loads((path / "dataset.json").read_text(encoding="utf-8"))
    assert data["version"] == manifest["version"] == 1
    tables = {entry["table"]["table"]: entry for entry in data["tables"]}
    assert {table: len(data["rows"]) for table, data in tables.items()} == _COUNTS
    assert {entry["table"]["table"]: entry["rows"] for entry in manifest["tables"]} == _COUNTS
    for child, key, parent in _EDGES:
        child_index = next(
            i for i, column in enumerate(tables[child]["columns"]) if column["name"] == key
        )
        parent_index = next(
            i for i, column in enumerate(tables[parent]["columns"]) if column["name"] == "id"
        )
        ids = {row[parent_index] for row in tables[parent]["rows"]}
        assert all(row[child_index] in ids for row in tables[child]["rows"])


def _reset(connection: Connection[Any]) -> None:
    connection.execute("DROP SCHEMA IF EXISTS ecommerce CASCADE")
    connection.execute((_ROOT / "tests/fixtures/ecommerce.sql").read_text(encoding="utf-8"))


def _summary(trials: list[dict[str, float | int]]) -> dict[str, object]:
    return {
        "trials": trials,
        "median_seconds": statistics.median(trial["elapsed_seconds"] for trial in trials),
        "highest_peak_rss_kib": max(trial["peak_rss_kib"] for trial in trials),
    }


def main() -> None:
    environment = _environment()
    # This harness owns the database process and has no external network access.
    url = os.environ["SEED_BENCHMARK_URL"]
    target = urlsplit(url)
    assert (target.hostname, target.port, target.path) == ("127.0.0.1", 5432, "/seed_benchmark")
    with (
        tempfile.TemporaryDirectory(prefix="seed-benchmark-") as temp,
        connect(url, autocommit=True) as connection,
    ):
        server = connection.execute(
            "SELECT current_database(), current_setting('server_version')"
        ).fetchone()
        assert server and server[0] == "seed_benchmark" and server[1].startswith("16.")
        environment["postgresql"] = server[1]
        directory = Path(temp)
        config = directory / "seed.toml"
        _config(config)
        apply_trials = []
        export_trials = []
        for trial in range(3):
            _reset(connection)
            apply_trials.append(_timed(directory, [str(_SEED)], "apply", "--yes"))
            _verify_database(connection, 1)

            _reset(connection)
            output = directory / f"json-{trial}"
            export_trials.append(
                _timed(
                    directory, [str(_SEED)], "export", "--format", "json", "--output", str(output)
                )
            )
            _verify_json(output)
            _verify_database(connection, 0)

        _reset(connection)
        _timed(directory, [str(_SEED)], "apply", "--yes")
        _config(config, append=True)
        append = _timed(
            directory,
            [sys.executable, str(Path(__file__).with_name("append_timing.py"))],
            "apply",
            "--yes",
        )
        _verify_database(connection, 2)
        timing = json.loads((directory / "append.json").read_text(encoding="utf-8"))
        assert timing["probe_count"] > 0 and timing["lock_seconds"] > 0
        print(
            json.dumps(
                {
                    "environment": environment,
                    "rows": sum(_COUNTS.values()),
                    "broken_references": 0,
                    "apply": _summary(apply_trials),
                    "json_export": _summary(export_trials),
                    "append": {**append, **timing},
                },
                indent=2,
            )
        )
        for trials in (apply_trials, export_trials):
            assert statistics.median(trial["elapsed_seconds"] for trial in trials) <= 60
            assert max(trial["peak_rss_kib"] for trial in trials) <= 256 * 1024


if __name__ == "__main__":
    main()
