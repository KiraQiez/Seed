"""Generate parent-first records from the typed offline plan."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from test_planning import column
from test_selection import sample

from seed.config import SeedConfig, parse_config
from seed.generation.engine import generate_batches
from seed.generation.streaming import GeneratedRecord, GenerationError
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
from seed.planning.plan import build_plan

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


def test_26500_reference_rows_follow_foreign_keys() -> None:
    from collections import Counter

    counts = {
        "customers": 1000,
        "products": 500,
        "orders": 5000,
        "items": 15000,
        "payments": 5000,
    }
    parents = {
        "orders": ("customers",),
        "items": ("orders", "products"),
        "payments": ("orders",),
    }
    schema = sample(*counts)
    templates = {table.id.table: table for table in schema.tables}
    models = []
    for name, table in templates.items():
        links = parents.get(name, ())
        identity, feature = _identity_model("id")
        models.append(
            table.model_copy(
                update={
                    "columns": (identity, *(column(f"{parent}_id") for parent in links)),
                    "features": (feature,),
                    "primary_key": Key(name="pk", columns=("id",)),
                    "unique_keys": (
                        UniqueKey(
                            name="junction",
                            columns=("orders_id", "products_id"),
                            supported=True,
                            nulls_distinct=True,
                        ),
                    )
                    if name == "items"
                    else (),
                    "foreign_keys": tuple(
                        foreign_key(templates[parent], (f"{parent}_id",), ("id",), parent)
                        for parent in links
                    ),
                }
            )
        )
    schema = schema.model_copy(update={"tables": tuple(models)})
    config = parse_config(
        BASE + "".join(f"[tables.{name}]\nrows={count}\n" for name, count in counts.items())
    )
    generated: Counter[str] = Counter()
    junction: set[tuple[object, object]] = set()
    for record in records(schema, config, batch_size=1000):
        name = record.table.table
        for parent in parents.get(name, ()):
            key_value = record.values[f"{parent}_id"]
            assert isinstance(key_value, int) and 1 <= key_value <= generated[parent]
        if name == "items":
            pair = record.values["orders_id"], record.values["products_id"]
            assert pair not in junction
            junction.add(pair)
        generated[name] += 1
        assert record.values["id"] == generated[name]
    assert dict(generated) == counts and generated.total() == 26_500


@pytest.mark.parametrize("distinct", [True, False])
def test_sql_unique_null_modes(distinct: bool) -> None:
    schema = sample("items")
    table = schema.tables[0].model_copy(
        update={
            "columns": (column("description", "text").model_copy(update={"nullable": True}),),
            "unique_keys": (
                UniqueKey(
                    name="unique_description",
                    columns=("description",),
                    supported=True,
                    nulls_distinct=distinct,
                ),
            ),
        }
    )
    schema = schema.model_copy(update={"tables": (table,)})
    config = parse_config(BASE + "[tables.items]\nrows=2\n[rules.items.description]\nnull_rate=1\n")
    if distinct:
        assert [row.values["description"] for row in records(schema, config)] == [None, None]
    else:
        with pytest.raises(GenerationError) as error:
            list(records(schema, config))
        assert error.value.issue.code == "DOMAIN_EXHAUSTED"
        assert error.value.issue.constraint == "unique_description"


def test_nonnullable_unique_foreign_capacity_is_checked() -> None:
    schema = sample("child", "parent")
    child, parent = schema.tables
    parent = parent.model_copy(update={"columns": (column("id"),)})
    child = child.model_copy(
        update={
            "columns": (column("parent_id"),),
            "primary_key": Key(name="pk", columns=("parent_id",)),
            "foreign_keys": (foreign_key(parent, ("parent_id",), ("id",)),),
        }
    )
    schema = schema.model_copy(update={"tables": (child, parent)})
    config = parse_config(BASE + "[tables.parent]\nrows=1\n[tables.child]\nrows=2\n")
    with pytest.raises(GenerationError) as captured:
        list(records(schema, config))
    assert captured.value.issue.code == "PARENT_KEYS_EXHAUSTED"


def test_candidate_reservations_are_atomic_for_composite_keys() -> None:
    from seed.generation.record_checks import UniqueReservations, UniqueRule

    tracked = UniqueReservations(
        (
            UniqueRule("pair", ("a", "b"), False),
            UniqueRule("c", ("c",), False),
        )
    )
    assert tracked.reserve({"a": 1, "b": 2, "c": 3})
    assert not tracked.reserve({"a": 1, "b": 4, "c": 3})
    assert tracked.reserve({"a": 1, "b": 4, "c": 5})
    assert not tracked.reserve({"a": 1, "b": 4, "c": 6})


def test_retries_collisions_without_exposing_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = sample("items")
    table = schema.tables[0].model_copy(update={"columns": (column("code", "text"),)})
    schema = schema.model_copy(update={"tables": (table,)})
    config = parse_config(BASE + "[tables.items]\nrows=2\n[rules.items.code]\nunique=true\n")
    monkeypatch.setattr("seed.generation.engine.scalar_value", lambda *args: "private-candidate")
    with pytest.raises(GenerationError) as captured:
        list(records(schema, config, batch_size=1))
    assert captured.value.issue.code == "RETRY_EXHAUSTED"
    assert captured.value.issue.ordinal == 1
    assert "private-candidate" not in str(captured.value)


def test_mixed_null_foreign_key_keeps_complete_tuple() -> None:
    schema = sample("child", "parent")
    child, parent = schema.tables
    parent = parent.model_copy(update={"columns": (column("a"), column("b"))})
    child = child.model_copy(
        update={
            "columns": (column("x").model_copy(update={"nullable": True}), column("y")),
            "foreign_keys": (foreign_key(parent, ("x", "y"), ("a", "b")),),
        }
    )
    schema = schema.model_copy(update={"tables": (child, parent)})
    config = parse_config(
        BASE.replace("null_rate=0", "null_rate=1")
        + "[tables.child]\nrows=2\n[tables.parent]\nrows=1\n"
    )
    parent_record, *children = records(schema, config)
    expected = (parent_record.values["a"], parent_record.values["b"])
    assert all((row.values["x"], row.values["y"]) == expected for row in children)
