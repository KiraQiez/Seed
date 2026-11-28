"""Publish a validated starter configuration without replacing existing files."""

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from seed.config import parse_config
from seed.planning.selection import MAX_ROWS

STARTER = """\
version = 1

[database]
driver = "postgresql"
url_env = "DATABASE_URL"
schema = "public"
"""


def initialize_config(path: Path, *, starter: Callable[[], str] | None = None) -> bool:
    """Return whether a new starter file was published."""
    try:
        return _publish(path, starter)
    except OSError:
        raise OSError("Could not create the configuration file.") from None


def _publish(path: Path, starter: Callable[[], str] | None) -> bool:
    if _existing_regular_file(path):
        return False

    contents = starter() if starter is not None else STARTER
    parse_config(contents)
    with TemporaryDirectory(prefix=".seed-init-", dir=path.parent) as directory:
        staged = Path(directory) / "seed.toml"
        with staged.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(contents)
        try:
            os.link(staged, path)
        except FileExistsError:
            if _existing_regular_file(path):
                return False
            raise
    return True


def guided_starter(prompt: Callable[[str], str], feedback: Callable[[str], None]) -> str:
    """Collect only the schema, tables, and row counts for a new config."""
    while True:
        schema = prompt("Schema [public]: ") or "public"
        if schema.isprintable() and schema.strip():
            break
        feedback("Enter a schema name with printable characters.")

    contents = STARTER.replace(
        'schema = "public"', f"schema = {json.dumps(schema, ensure_ascii=False)}"
    )
    tables: set[str] = set()
    remaining = MAX_ROWS
    while remaining:
        question = "Table name: " if not tables else "Another table (Enter to finish): "
        table = prompt(question)
        if not table and tables:
            break
        if not table.isprintable() or not table.strip():
            feedback("Enter an exact table name with printable characters.")
            continue
        if table in tables:
            feedback("That table is already selected. Enter a different table.")
            continue
        default = min(10, remaining)
        while True:
            answer = prompt(f"Rows to generate [{default}]: ").strip()
            try:
                rows = int(answer) if answer else default
            except ValueError:
                rows = 0
            if 1 <= rows <= remaining:
                break
            feedback(f"Enter a whole number from 1 to {remaining:,}.")
        tables.add(table)
        remaining -= rows
        contents += f"\n[tables.{json.dumps(table, ensure_ascii=False)}]\nrows = {rows}\n"
    return contents


def _existing_regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise OSError("Configuration path is not a regular file.")
    return True
