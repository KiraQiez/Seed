"""Table selection and count precedence."""

import pytest

from seed.config import ConfigError, parse_config
from seed.database import DatabaseError
from seed.metadata import DatabaseSchema, TableId, TableSchema, Target
from seed.selection import resolve_selection

_BASE = 'version=1\n[database]\nurl_env="DATABASE_URL"\n'


def sample(*names: str) -> DatabaseSchema:
    return DatabaseSchema(
        target=Target(host="localhost", port=5432, database="test", schema="Seed.Scope"),
        server_major=17,
        schemas=("Seed.Scope",),
        tables=tuple(
            TableSchema(id=TableId(schema="Seed.Scope", table=name), kind="r", columns=())
            for name in names
        ),
        fingerprint="fixture",
    )


def test_selection_and_count_precedence() -> None:
    config = parse_config(_BASE + '[tables."Order.Item"]\nrows=0\n')
    schema = sample("Order.Item", 'A"B')
    assert resolve_selection(config, schema, []).requested == ("Order.Item",)
    selected = resolve_selection(config, schema, ['"Seed.Scope"."A""B"'], 12)
    assert selected.requested == ('A"B',)
    assert selected.counts == {"Order.Item": 0, 'A"B': 12}
    with pytest.raises(ConfigError):
        resolve_selection(config, schema, ['"A""B"', '"A""B"'], 0)


@pytest.mark.parametrize("name", ["unknown", 'other."Order.Item"'])
def test_rejects_unknown_or_wrong_schema(name: str) -> None:
    with pytest.raises(DatabaseError):
        resolve_selection(parse_config(_BASE), sample("Order.Item"), [name])


def test_reuse_requires_zero_count() -> None:
    config = parse_config(_BASE + "[tables.parent]\nrows=0\nreuse_existing=true\n")
    with pytest.raises(ConfigError):
        resolve_selection(config, sample("parent"), ["parent"], 1)
