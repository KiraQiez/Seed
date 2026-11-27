"""Starter publication tests."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from seed.config import load_config
from seed.workflows.initialize import initialize_config


def test_concurrent_initializers_publish_one_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "seed.toml"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(initialize_config, [path] * 4))
    assert results.count(True) == 1
    assert load_config(path).database.url_env == "DATABASE_URL"
    assert list(tmp_path.iterdir()) == [path]


def test_preserves_existing_bytes(tmp_path: Path) -> None:
    path = tmp_path / "seed.toml"
    path.write_bytes(b"custom contents")
    assert initialize_config(path) is False
    assert path.read_bytes() == b"custom contents"


def test_refuses_directory(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        initialize_config(tmp_path)


def test_refuses_symlink(tmp_path: Path) -> None:
    path = tmp_path / "seed.toml"
    target = tmp_path / "untouched"
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks are unavailable on this runner")
    with pytest.raises(OSError):
        initialize_config(path)
    assert path.is_symlink()
    assert not target.exists()
