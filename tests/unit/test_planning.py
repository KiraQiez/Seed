"""Typed plans, bindings, and execution-mode compatibility."""

from test_dependencies import key
from test_selection import sample

from seed.config import parse_config
from seed.metadata import ColumnSchema, ColumnType, Feature
from seed.planning import build_plan

_BASE = 'version=1\n[database]\nurl_env="DATABASE_URL"\n'


def column(name: str, kind: str = "integer") -> ColumnSchema:
    return ColumnSchema(
        name=name,
        ordinal=1,
        type=ColumnType(name=kind, supported=True),
        nullable=False,
        default_kind="none",
    )


def test_reference_plan_is_stable_and_totals_26500() -> None:
    counts = {"customers": 1000, "products": 500, "orders": 5000, "items": 15000, "payments": 5000}
    schema = sample(*counts)
    links = {
        "orders": ("customers",),
        "items": ("orders", "products"),
        "payments": ("orders",),
    }
    schema = schema.model_copy(
        update={
            "tables": tuple(
                table.model_copy(
                    update={
                        "columns": (
                            column("id"),
                            *(column(f"{parent}_id") for parent in links.get(table.id.table, ())),
                        ),
                        "foreign_keys": tuple(
                            key(parent, parent).model_copy(
                                update={
                                    "columns": (f"{parent}_id",),
                                    "parent_columns": ("id",),
                                }
                            )
                            for parent in links.get(table.id.table, ())
                        ),
                    }
                )
                for table in schema.tables
            )
        }
    )
    config = parse_config(
        _BASE + "".join(f"[tables.{name}]\nrows={count}\n" for name, count in counts.items())
    )
    plan = build_plan(config, schema, [])
    assert plan.total_rows == 26500 and plan.executable
    assert plan.model_dump_json() == build_plan(config, schema, []).model_dump_json()
    assert plan.tables[0].bindings["live"][0].generator == "integer"
    positions = {table.id.table: index for index, table in enumerate(plan.tables)}
    assert all(
        positions[parent] < positions[child]
        for child, parents in links.items()
        for parent in parents
    )


def test_limit_applies_after_dependency_expansion() -> None:
    schema = sample("child", "parent")
    child, parent = schema.tables
    schema = schema.model_copy(
        update={
            "tables": (
                child.model_copy(
                    update={"columns": (column("id"),), "foreign_keys": (key("fk", "parent"),)}
                ),
                parent.model_copy(update={"columns": (column("id"),)}),
            )
        }
    )
    config = parse_config(_BASE + "[generation]\ndefault_rows=50001\n")
    plan = build_plan(config, schema, ["child"])
    assert plan.total_rows == 100002
    assert not plan.executable
    assert "ROW_LIMIT_EXCEEDED" in {issue.code for issue in plan.compatibility["live"].issues}


def test_existing_parent_disables_only_offline_plan() -> None:
    schema = sample("child", "parent")
    child, parent = schema.tables
    schema = schema.model_copy(
        update={
            "tables": (
                child.model_copy(
                    update={
                        "columns": (column("first"), column("second")),
                        "foreign_keys": (key("fk", "parent"),),
                    }
                ),
                parent,
            )
        }
    )
    config = parse_config(_BASE + "[tables.parent]\nrows=0\nreuse_existing=true\n")
    plan = build_plan(config, schema, ["child"])
    assert plan.compatibility["live"].executable
    assert not plan.compatibility["offline"].executable
    assert [table.key_source for table in plan.tables] == ["existing", "generated"]


def test_offline_sequence_limit_is_mode_specific() -> None:
    schema = sample("items")
    identity = column("id").model_copy(update={"default_kind": "identity", "sequence_max": 5})
    schema = schema.model_copy(
        update={
            "tables": (
                schema.tables[0].model_copy(
                    update={
                        "columns": (identity,),
                        "features": (
                            Feature(
                                name="sequence id", status="Partial", reason="SERVER_ALLOCATED_KEY"
                            ),
                        ),
                    }
                ),
            )
        }
    )
    good = build_plan(parse_config(_BASE), schema, ["items"], 5)
    assert all(mode.executable for mode in good.compatibility.values())
    bad = build_plan(parse_config(_BASE), schema, ["items"], 6)
    assert bad.compatibility["live"].executable
    assert not bad.compatibility["offline"].executable


def test_rule_incompatible_with_column_type_is_blocked() -> None:
    schema = sample("items")
    schema = schema.model_copy(
        update={"tables": (schema.tables[0].model_copy(update={"columns": (column("id"),)}),)}
    )
    plan = build_plan(
        parse_config(_BASE + '[rules.items.id]\ngenerator="constant"\nvalue="private-value"\n'),
        schema,
        [],
    )
    assert not plan.executable
    assert "private-value" not in plan.model_dump_json()
    assert plan.compatibility["live"].issues[0].code == "INCOMPATIBLE_BINDING"


def test_numeric_choices_must_be_distinct_after_conversion() -> None:
    schema = sample("items")
    schema = schema.model_copy(
        update={
            "tables": (
                schema.tables[0].model_copy(update={"columns": (column("amount", "numeric"),)}),
            )
        }
    )
    plan = build_plan(
        parse_config(_BASE + '[rules.items.amount]\ngenerator="choice"\nvalues=["1", "1.0"]\n'),
        schema,
        [],
    )
    assert not plan.executable
