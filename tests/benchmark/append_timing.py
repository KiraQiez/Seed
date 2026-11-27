"""Collect SQL timing for the append trial without logging values or statements."""

import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import Connection, event
from sqlalchemy.engine import Engine

from seed.cli import main

_timing: dict[str, float | int] = {"lock_seconds": 0.0, "probe_seconds": 0.0, "probe_count": 0}


@event.listens_for(Engine, "before_cursor_execute")
def _before(
    connection: Connection,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    if statement.startswith("LOCK TABLE ONLY "):
        context.seed_benchmark = ("lock_seconds", perf_counter())
    elif statement.startswith("SELECT EXISTS") and "FROM ONLY" not in statement:
        context.seed_benchmark = ("probe_seconds", perf_counter())


@event.listens_for(Engine, "after_cursor_execute")
def _after(
    connection: Connection,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    timing = getattr(context, "seed_benchmark", None)
    if timing is not None:
        label, start = timing
        _timing[label] += perf_counter() - start
        if label == "probe_seconds":
            _timing["probe_count"] += 1


if __name__ == "__main__":
    try:
        status = main()
    finally:
        Path(os.environ["SEED_APPEND_TIMING"]).write_text(json.dumps(_timing), encoding="utf-8")
    raise SystemExit(status)
