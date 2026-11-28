"""Render a Homebrew formula with checksum-pinned source and wheel resources."""

import argparse
import json
import re
import tomllib
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urlsplit

from packaging.markers import Marker
from packaging.tags import compatible_tags, cpython_tags, mac_platforms
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version
from release_artifacts import digest

from seed import __version__

_ROOT = Path(__file__).resolve().parents[1]
_PYTHON = (3, 14)
type Wheel = tuple[str, str]


def _filename(url: str) -> str:
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or target.netloc != "files.pythonhosted.org"
        or target.query
        or target.fragment
        or not re.fullmatch(r"/packages/[a-zA-Z0-9./_%+-]+", target.path)
    ):
        raise ValueError("Expected a canonical PyPI file URL.")
    return target.path.rsplit("/", 1)[-1]


def _wheels(packages: list[dict[str, Any]], system: str, arch: str) -> dict[str, Wheel]:
    platforms = (
        list(mac_platforms((14, 0), arch))
        if system == "darwin"
        else [
            *(f"manylinux_2_{minor}_x86_64" for minor in range(28, 16, -1)),
            "manylinux2014_x86_64",
        ]
    )
    tags = {
        tag: priority
        for priority, tag in enumerate(
            [
                *cpython_tags(_PYTHON, platforms=platforms),
                *compatible_tags(_PYTHON, platforms=platforms),
            ]
        )
    }
    environment = {
        "implementation_name": "cpython",
        "implementation_version": "3.14.0",
        "os_name": "posix",
        "platform_machine": arch,
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Darwin" if system == "darwin" else "Linux",
        "platform_version": "",
        "python_full_version": "3.14.0",
        "python_version": "3.14",
        "sys_platform": system,
    }
    selected: dict[str, Wheel] = {}
    for package in packages:
        if "marker" in package and not Marker(package["marker"]).evaluate(environment):
            continue
        name = package["name"]
        if system == "darwin" and name == "psycopg-binary":
            continue
        choices: list[tuple[int, str, str]] = []
        for wheel in package.get("wheels", []):
            url = wheel["url"]
            wheel_name, version, _, wheel_tags = parse_wheel_filename(_filename(url))
            if wheel_name != canonicalize_name(name) or version != Version(package["version"]):
                raise ValueError(f"Incorrect lockfile wheel identity for {name}.")
            matched = wheel_tags & tags.keys()
            if matched:
                checksum = wheel["hashes"]["sha256"]
                if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                    raise ValueError(f"Invalid lockfile wheel checksum for {name}.")
                choices.append((min(tags[tag] for tag in matched), url, checksum))
        if name in selected or not choices:
            raise ValueError(f"Expected locked wheel for {name} on {system} {arch}.")
        _, url, checksum = min(choices)
        selected[name] = (url, checksum)
    return selected


def _resource(name: str, wheel: Wheel, indent: str = "  ") -> str:
    url, checksum = wheel
    return (
        f'{indent}resource "{name}" do\n'
        f'{indent}  url "{url}", using: :nounzip\n'
        f'{indent}  sha256 "{checksum}"\n'
        f"{indent}end"
    )


def _resources(packages: list[dict[str, Any]]) -> str:
    arm, intel, linux = (
        _wheels(packages, system, arch)
        for system, arch in (("darwin", "arm64"), ("darwin", "x86_64"), ("linux", "x86_64"))
    )
    blocks = []
    for name in sorted(arm.keys() | intel.keys() | linux.keys()):
        if name in arm and arm[name] == intel.get(name) == linux.get(name):
            blocks.append(_resource(name, arm[name]))
            continue
        if name in linux:
            blocks.append(f"  on_linux do\n{_resource(name, linux[name], '    ')}\n  end")
        if name in arm or name in intel:
            mac = []
            if name in arm and arm[name] == intel.get(name):
                mac.append(_resource(name, arm[name], "    "))
            else:
                for arch, wheels in (("arm", arm), ("intel", intel)):
                    if name in wheels:
                        mac.append(
                            f"    on_{arch} do\n{_resource(name, wheels[name], '      ')}\n    end"
                        )
            blocks.append("  on_macos do\n" + "\n".join(mac) + "\n  end")
    return "\n\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist", type=Path)
    parser.add_argument("lock", type=Path, help="uv export of runtime and build dependencies")
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-url", help="Public PyPI URL of the verified sdist")
    args = parser.parse_args()

    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    expected = f"{project['name'].replace('-', '_')}-{__version__}.tar.gz"
    if args.sdist.name != expected or (args.source_url and _filename(args.source_url) != expected):
        parser.error(f"Expected exact source distribution {expected}.")
    packages = tomllib.loads(args.lock.read_text(encoding="utf-8"))["packages"]
    template = Template((_ROOT / "packaging/homebrew/seed.rb.in").read_text(encoding="utf-8"))
    formula = template.substitute(
        description=json.dumps(project["description"]),
        source_url=json.dumps(args.source_url or args.sdist.resolve().as_uri()),
        version=json.dumps(__version__),
        checksum=json.dumps(digest(args.sdist)),
        resources=_resources(packages),
    )
    args.output.write_text(formula, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
