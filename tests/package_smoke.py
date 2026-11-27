"""Build and verify wheel installs outside the source tree."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from seed import __version__


def _run(args: list[str], directory: Path) -> str:
    return subprocess.check_output(
        args,
        cwd=directory,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=180,
    )


def verify_dist(directory: Path) -> None:
    """Rebuild a wheel from the sdist and smoke-test both standalone wheels."""
    directory = directory.resolve()
    (wheel,) = directory.glob("*.whl")
    (sdist,) = directory.glob("*.tar.gz")
    with tempfile.TemporaryDirectory(prefix="seed-wheel-") as temp_name:
        scratch = Path(temp_name)
        rebuilt = scratch / "rebuilt"
        _run(["uv", "build", "--wheel", str(sdist), "--out-dir", str(rebuilt)], scratch)
        (rebuilt_wheel,) = rebuilt.glob("*.whl")
        for index, artifact in enumerate((wheel, rebuilt_wheel), start=1):
            work = scratch / f"install-{index}"
            work.mkdir()
            command = [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--python",
                sys.executable,
                "--with",
                str(artifact),
                "seed",
            ]
            assert _run([*command, "--version"], work).strip() == __version__
            help_text = _run([*command, "--help"], work)
            assert all(name in help_text for name in ("init", "apply", "export"))
            status = json.loads(_run([*command, "init", "--json"], work))
            config = tomllib.loads((work / "seed.toml").read_text(encoding="utf-8"))
            assert status["ok"] and status["data"]["created"]
            assert config["version"] == 1 and config["database"]["url_env"] == "DATABASE_URL"
        for artifact in (sdist, wheel, rebuilt_wheel):
            print(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}")


if __name__ == "__main__":
    verify_dist(Path(sys.argv[1]))
