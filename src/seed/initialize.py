"""Publish a validated starter configuration without replacing existing files."""

import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

from seed.config import parse_config

STARTER = """\
version = 1

[database]
driver = "postgresql"
url_env = "DATABASE_URL"
schema = "public"
"""


def initialize_config(path: Path) -> bool:
    """Return whether a new starter file was published."""
    try:
        return _publish(path)
    except OSError:
        raise OSError("Could not create the configuration file.") from None


def _publish(path: Path) -> bool:
    if _existing_regular_file(path):
        return False

    parse_config(STARTER)
    with TemporaryDirectory(prefix=".seed-init-", dir=path.parent) as directory:
        staged = Path(directory) / "seed.toml"
        with staged.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(STARTER)
        try:
            os.link(staged, path)
        except FileExistsError:
            if _existing_regular_file(path):
                return False
            raise
    return True


def _existing_regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise OSError("Configuration path is not a regular file.")
    return True
