"""Build and verify wheel installs outside the source tree."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from seed import __version__


def _run(args: list[str], directory: Path, extra_env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(
        args,
        cwd=directory,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", **(extra_env or {})},
        timeout=180,
    )


def _smoke(command: list[str], work: Path) -> None:
    assert _run([*command, "--version"], work).strip() == __version__
    help_text = _run([*command, "--help"], work)
    assert all(name in help_text for name in ("init", "apply", "export"))
    status = json.loads(_run([*command, "init", "--json"], work))
    config = tomllib.loads((work / "seed.toml").read_text(encoding="utf-8"))
    assert status["ok"] and status["data"]["created"]
    assert config["version"] == 1 and config["database"]["url_env"] == "DATABASE_URL"


def verify_tools(package: str, scratch: Path) -> None:
    executable = "seed.exe" if os.name == "nt" else "seed"
    for installer, command, bin_var, home_var in (
        ("uv", ["uv", "tool"], "UV_TOOL_BIN_DIR", "UV_TOOL_DIR"),
        ("pipx", ["uvx", "--from", "pipx==1.9.0", "pipx"], "PIPX_BIN_DIR", "PIPX_HOME"),
    ):
        work = scratch / installer
        work.mkdir()
        bin_dir = work / "bin"
        _run(
            [*command, "install", "--python", sys.executable, package],
            work,
            {bin_var: str(bin_dir), home_var: str(work / "tools")},
        )
        _smoke([str(bin_dir / executable)], work)


def verify_dist(directory: Path, *, tools: bool = False) -> None:
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
            _smoke(command, work)
        if tools:
            verify_tools(str(wheel), scratch)
        for artifact in (sdist, wheel, rebuilt_wheel):
            print(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Distribution directory or pinned index requirement")
    parser.add_argument("--tools", action="store_true", help="Also verify uv tool and pipx")
    parser.add_argument("--index", action="store_true", help="Install a pinned published release")
    args = parser.parse_args()
    if args.index:
        with tempfile.TemporaryDirectory(prefix="seed-index-") as temp_name:
            verify_tools(args.target, Path(temp_name))
    else:
        verify_dist(Path(args.target), tools=args.tools)
