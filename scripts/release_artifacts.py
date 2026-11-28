"""Validate release refs, package contents, and distribution checksums."""

import argparse
import configparser
import hashlib
import os
import re
import tarfile
import tomllib
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from packaging.requirements import Requirement

from seed import __version__

_ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def release_notes() -> Path:
    tag = f"v{__version__}"
    ref = os.environ.get("GITHUB_REF", "refs/heads/staging")
    if ref not in {"refs/heads/staging", f"refs/tags/{tag}"}:
        raise ValueError(f"Release ref must be staging or the package tag {tag}.")
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[{re.escape(__version__)}\] ", changelog, re.MULTILINE):
        raise ValueError("Changelog has no entry for the package version.")
    notes = _ROOT / "docs" / "releases" / f"{tag}.md"
    if not notes.read_text(encoding="utf-8").startswith(f"# Seed {tag}\n"):
        raise ValueError("Release notes do not match the package version.")
    return notes


def _metadata(raw: bytes, project: dict[str, Any]) -> None:
    metadata = BytesParser().parsebytes(raw)
    for header, expected in (
        ("Name", project["name"]),
        ("Version", __version__),
        ("Requires-Python", project["requires-python"]),
        ("License-Expression", project["license"]),
    ):
        if metadata[header] != expected:
            raise ValueError(f"Unexpected package metadata field {header}.")
    if metadata.get_all("License-File") != project["license-files"]:
        raise ValueError("Unexpected package licence files.")
    if {Requirement(value) for value in metadata.get_all("Requires-Dist", [])} != {
        Requirement(value) for value in project["dependencies"]
    }:
        raise ValueError("Unexpected runtime dependencies.")


def _contents(wheel: Path, sdist: Path, project: dict[str, Any], stem: str) -> None:
    source = _ROOT / "src"
    sources = {
        item.relative_to(source).as_posix(): item.read_bytes()
        for item in (source / "seed").rglob("*.py")
    }
    licence = (_ROOT / "LICENSE").read_bytes()
    info = f"{stem}.dist-info"
    with ZipFile(wheel) as archive:
        metadata = {"METADATA", "WHEEL", "RECORD", "entry_points.txt", "licenses/LICENSE"}
        if set(archive.namelist()) != sources.keys() | {f"{info}/{name}" for name in metadata}:
            raise ValueError("Unexpected files in wheel.")
        for name, expected in sources.items():
            if archive.read(name) != expected:
                raise ValueError(f"Wheel source differs from checkout for {name}.")
        _metadata(archive.read(f"{info}/METADATA"), project)
        entry = configparser.ConfigParser()
        entry.read_string(archive.read(f"{info}/entry_points.txt").decode())
        if dict(entry["console_scripts"]) != project["scripts"]:
            raise ValueError("Unexpected wheel entry point.")
        if archive.read(f"{info}/licenses/LICENSE") != licence:
            raise ValueError("Wheel licence differs from checkout.")
    with tarfile.open(sdist) as archive:
        expected_files = {
            **{f"src/{name}": data for name, data in sources.items()},
            **{
                name: (_ROOT / name).read_bytes()
                for name in (".gitignore", "LICENSE", "pyproject.toml", "docs/PYPI.md")
            },
        }
        members = archive.getmembers()
        expected_names = {f"{stem}/{name}" for name in expected_files.keys() | {"PKG-INFO"}}
        if {member.name for member in members} != expected_names or not all(
            member.isfile() for member in members
        ):
            raise ValueError("Unexpected files in source distribution.")
        for member in members:
            name = member.name.removeprefix(f"{stem}/")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Missing source archive entry {name}.")
            with stream:
                data = stream.read()
            if name == "PKG-INFO":
                _metadata(data, project)
            elif data != expected_files[name]:
                raise ValueError(f"Source archive differs from checkout for {name}.")


def verify(directory: Path, *, record: bool) -> None:
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    stem = f"{project['name'].replace('-', '_')}-{__version__}"
    wheel = directory / f"{stem}-py3-none-any.whl"
    sdist = directory / f"{stem}.tar.gz"
    manifest = directory / "SHA256SUMS"
    expected = {wheel.name, sdist.name}
    if not record:
        expected.add(manifest.name)
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError("Unexpected release distribution files.")
    checksums = "".join(f"{digest(path)}  {path.name}\n" for path in (wheel, sdist))
    if record:
        _contents(wheel, sdist, project, stem)
        manifest.write_text(checksums, encoding="ascii", newline="\n")
    elif manifest.read_text(encoding="ascii") != checksums:
        raise ValueError("Release distribution checksums do not match.")
    print(checksums, end="")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--notes", type=Path, help="Validate the build and record release notes")
    args = parser.parse_args()
    notes = release_notes() if args.notes else None
    verify(args.directory, record=notes is not None)
    if notes is not None:
        args.notes.write_bytes(notes.read_bytes())


if __name__ == "__main__":
    main()
