import json
import os
from pathlib import Path

import pytest

from seed.export_files import ExportFileError, export_directory


def test_existing_file_directory_and_symlink_are_preserved(tmp_path: Path) -> None:
    file = tmp_path / "file"
    file.write_text("keep", encoding="utf-8")
    directory = tmp_path / "directory"
    directory.mkdir()
    for path in (file, directory):
        with pytest.raises(ExportFileError, match="already exists"), export_directory(path):
            pytest.fail("existing path opened")
    assert file.read_text(encoding="utf-8") == "keep"
    assert list(directory.iterdir()) == []
    if os.name != "nt":
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "missing")
        with pytest.raises(ExportFileError, match="already exists"), export_directory(link):
            pytest.fail("symlink opened")
        assert link.is_symlink()


def test_manifest_is_visible_only_after_artifacts_close(tmp_path: Path) -> None:
    path = tmp_path / "export"
    with export_directory(path) as output:
        with output.artifact("dataset.json") as artifact:
            artifact.write("[]")
            assert not (path / "manifest.json").exists()
            with pytest.raises(OSError, match="incomplete"):
                output.publish({"version": 1})
        output.publish({"version": 1})
    assert json.loads((path / "manifest.json").read_text()) == {"version": 1}
    assert sorted(child.name for child in path.iterdir()) == ["dataset.json", "manifest.json"]


def test_failed_export_cleans_owned_files_only(tmp_path: Path) -> None:
    path = tmp_path / "export"
    with (
        pytest.raises(ExportFileError, match="finish writing"),
        export_directory(path) as output,
        output.artifact("dataset.json") as artifact,
    ):
        artifact.write("partial")
        (path / "unowned").write_text("keep", encoding="utf-8")
        raise OSError("simulated write failure with sensitive detail")
    assert sorted(child.name for child in path.iterdir()) == ["unowned"]

    incomplete = tmp_path / "incomplete"
    with pytest.raises(ExportFileError), export_directory(incomplete):
        pass
    assert not incomplete.exists()


def test_refuses_a_replaced_artifact_and_preserves_the_replacement(tmp_path: Path) -> None:
    path = tmp_path / "export"
    replacement = tmp_path / "replacement"
    replacement.write_text("keep", encoding="utf-8")
    with pytest.raises(ExportFileError, match="finish writing"), export_directory(path) as output:
        with output.artifact("dataset.json") as artifact:
            artifact.write("generated")
        replacement.replace(path / "dataset.json")
        output.publish({"version": 1})
    assert (path / "dataset.json").read_text(encoding="utf-8") == "keep"
    assert not (path / "manifest.json").exists()
