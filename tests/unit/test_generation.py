"""Generate parent-first records from the typed offline plan."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from test_planning import column
from test_selection import sample

from seed.config import SeedConfig, parse_config
from seed.generation import generate_batches
from seed.metadata import (
    ColumnSchema,
    DatabaseSchema,
    Feature,
    ForeignKey,
    Key,
    TableId,
    TableSchema,
    UniqueKey,
)
from seed.planning import build_plan
from seed.streaming import GeneratedRecord, GenerationError

BASE = 'version=1\n[database]\nurl_env="DATABASE_URL"\n[generation]\nnull_rate=0\n'


def records(
    schema: DatabaseSchema,
    config: SeedConfig,
    *,
    batch_size: int = 20,
) -> Iterator[GeneratedRecord]:
    plan = build_plan(config, schema, [])
    for batch in generate_batches(plan, schema, config, batch_size=batch_size):
        assert 0 < len(batch) <= batch_size
        assert len({row.table for row in batch}) == 1
        yield from batch


def foreign_key(
    parent: TableSchema,
    columns: tuple[str, ...],
    referenced: tuple[str, ...],
    name: str = "parent_fk",
) -> ForeignKey:
    return ForeignKey(
        name=name,
        columns=columns,
        parent=parent.id,
        parent_columns=referenced,
        validated=True,
        enforced=True,
    )


def _identity_model(name: str) -> tuple[ColumnSchema, Feature]:
    return column(name).model_copy(
        update={"default_kind": "identity", "sequence_max": 100_000}
    ), Feature(
        name=f"sequence {name}",
        status="Partial",
        reason="SERVER_ALLOCATED_KEY",
    )


def test_composite_uuid_text_parent_and_strip_computed_column() -> None:
    schema = sample("child", "parent")
    child, parent = schema.tables
    parent = parent.model_copy(
        update={
            "columns": (column("code", "text"), column("group", "uuid")),
            "primary_key": Key(name="pk", columns=("code", "group")),
        }
    )
    identity, feature = _identity_model("id")
    child = child.model_copy(
        update={
            "columns": (
                identity,
                column("label", "text"),
                column("group", "uuid"),
                column("computed").model_copy(update={"generated": "stored"}),
            ),
            "features": (feature,),
            "foreign_keys": (foreign_key(parent, ("label", "group"), ("code", "group")),),
            "unique_keys": (
                UniqueKey(
                    name="pair", columns=("label", "group"), supported=True, nulls_distinct=True
                ),
            ),
        }
    )
    schema = schema.model_copy(update={"tables": (child, parent)})
    config = parse_config(BASE + "[tables.parent]\nrows=7\n[tables.child]\nrows=7\n")
    result = list(records(schema, config, batch_size=3))
    assert result == list(records(schema, config, batch_size=11))
    parent_keys = {(row.values["code"], row.values["group"]) for row in result[:7]}
    child_keys = {(row.values["label"], row.values["group"]) for row in result[7:]}
    assert parent_keys == child_keys
    assert all(isinstance(value, UUID) for _, value in child_keys)
    for index, row in enumerate(result[7:]):
        assert row.ordinal == index and row.values["id"] == index + 1
        assert list(row.values) == ["id", "label", "group"]


def test_depleted_pool_has_scoped_failure() -> None:
    schema = sample("child", "parent")
    child, parent = schema.tables
    parent = parent.model_copy(
        update={"columns": (column("key").model_copy(update={"nullable": True}),)}
    )
    child = child.model_copy(
        update={
            "columns": (column("key"),),
            "foreign_keys": (foreign_key(parent, ("key",), ("key",)),),
        }
    )
    schema = schema.model_copy(update={"tables": (child, parent)})
    config = parse_config(
        BASE + "[tables.child]\nrows=1\n[tables.parent]\nrows=1\n[rules.parent.key]\nnull_rate=1\n"
    )
    with pytest.raises(GenerationError) as captured:
        list(records(schema, config))
    assert captured.value.issue.code == "PARENT_KEYS_EXHAUSTED"
    assert captured.value.issue.table == TableId(schema="Seed.Scope", table="child")


def test_schema_mismatch_and_offline_block_are_rejected() -> None:
    schema = sample("items")
    table = schema.tables[0].model_copy(update={"columns": (column("id"),)})
    schema = schema.model_copy(update={"tables": (table,)})
    config = parse_config(BASE + "[tables.items]\nrows=1\n")
    plan = build_plan(config, schema, [])
    stale = schema.model_copy(update={"fingerprint": "changed"})
    with pytest.raises(GenerationError) as captured:
        list(generate_batches(plan, stale, config))
    assert captured.value.issue.code == "INVALID_PLAN"
    blocked = build_plan(config, schema, []).model_copy(update={"compatibility": {}})
    with pytest.raises(GenerationError) as captured:
        list(generate_batches(blocked, schema, config))
    assert captured.value.issue.code == "PLAN_BLOCKED"
