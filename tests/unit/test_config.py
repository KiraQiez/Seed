"""Configuration contract tests."""

import re
from pathlib import Path

import pytest

from seed.config import ConfigError, load_config, parse_config, resolve_database_url

STARTER = 'version = 1\n[database]\nurl_env = "DATABASE_URL"\n'


def test_documented_configuration_and_defaults() -> None:
    docs = Path("docs/DATA_MODEL.md").read_text(encoding="utf-8")
    example = re.search(r"```toml\n(.*?)```", docs, re.DOTALL)
    assert example is not None
    config = parse_config(example[1])
    assert config.tables["customers"].rows == 1000
    assert config.database.connect_timeout == 5
    assert config.safety.target is not None
    assert config.safety.target.schema_name == "public"
    assert config.generation.batch_size == 1000


def test_overrides() -> None:
    config = parse_config(STARTER, schema="Sales", random_seed=42, locale="en_GB")
    assert config.database.schema_name == "Sales"
    assert config.generation.random_seed == 42
    assert config.generation.locale == "en_GB"


@pytest.mark.parametrize("text", [
    STARTER.replace("= 1", "= 2"),
    STARTER.replace("= 1", "= true"),
    'version = 1\nunknown = "private-value"\n[database]\nurl_env = "DATABASE_URL"\n',
    STARTER + 'password = "private-value"\n',
    STARTER + '[generation]\nlocale = "private-value"\n',
    STARTER + '[rules.users.age]\ngenerator = "integer"\nmin = "private-value"\n',
    STARTER + '[rules.users.age]\ngenerator = "decimal"\nmin = "NaN"\n',
    STARTER + '[rules.users.age]\ngenerator = "choice"\nvalues = [1, 1]\n',
    STARTER + '[tables.users]\nreuse_existing = true\n',
    STARTER + 'broken = "private-value\n',
])
def test_invalid_input_is_redacted(text: str) -> None:
    with pytest.raises(ConfigError) as error:
        parse_config(text)
    assert "private-value" not in str(error.value)


def test_credentials_are_separate_from_loading(tmp_path: Path) -> None:
    path = tmp_path / "seed.toml"
    path.write_text(STARTER, encoding="utf-8")
    config = load_config(path)
    with pytest.raises(ConfigError, match="missing or empty"):
        resolve_database_url(config, {})
    assert resolve_database_url(config, {"DATABASE_URL": "value-from-environment"}) == "value-from-environment"
