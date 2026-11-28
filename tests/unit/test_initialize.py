"""Starter publication tests."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from seed.config import load_config
from seed.workflows.initialize import guided_starter, initialize_config


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

    def unexpected_prompt() -> str:
        pytest.fail("Existing config should skip setup")

    assert initialize_config(path, starter=unexpected_prompt) is False
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


def test_guided_setup_validates_answers_and_quotes_exact_names(tmp_path: Path) -> None:
    path = tmp_path / "seed.toml"
    answers = iter(["", "", 'Order."Line"', "", 'Order."Line"', "customers", "0", "x", "5", ""])
    feedback: list[str] = []

    assert initialize_config(
        path, starter=lambda: guided_starter(lambda _: next(answers), feedback.append)
    )
    config = load_config(path)
    assert config.database.schema_name == "public"
    assert config.database.url_env == "DATABASE_URL"
    assert {name: table.rows for name, table in config.tables.items()} == {
        'Order."Line"': 10,
        "customers": 5,
    }
    assert len(feedback) == 4
    assert config.safety.target is None


def test_guided_setup_respects_total_row_budget(tmp_path: Path) -> None:
    path = tmp_path / "seed.toml"
    answers = iter(["My schema", "orders", "99999", "customers", "2", ""])
    feedback: list[str] = []
    initialize_config(
        path, starter=lambda: guided_starter(lambda _: next(answers), feedback.append)
    )
    config = load_config(path)
    assert config.database.schema_name == "My schema"
    assert config.tables["customers"].rows == 1
    assert feedback == ["Enter a whole number from 1 to 1."]
