"""Dependency expansion and deterministic ordering."""

from test_selection import sample

from seed.metadata import ColumnSchema, ColumnType, ForeignKey, TableId
from seed.planning.dependencies import resolve_dependencies
from seed.planning.selection import Selection


def key(name: str, parent: str) -> ForeignKey:
    return ForeignKey(
        name=name,
        columns=("first", "second"),
        parent=TableId(schema="Seed.Scope", table=parent),
        parent_columns=("a", "b"),
        validated=True,
        enforced=True,
    )


def test_multi_parent_order_preserves_composite_keys() -> None:
    tables = {
        table.id.table: table for table in sample("link", "z_parent", "a_parent", "unused").tables
    }
    tables["link"] = tables["link"].model_copy(
        update={
            "foreign_keys": (key("z", "z_parent"), key("a", "a_parent")),
        }
    )
    graph = resolve_dependencies(
        Selection(("link",), tables, dict.fromkeys(tables, 2), frozenset()), 0
    )
    assert graph.order == ("a_parent", "z_parent", "link")
    assert graph.dependencies["link"][0].key.parent_columns == ("a", "b")
    assert not graph.issues


def test_cycles_self_references_and_missing_parents() -> None:
    tables = {table.id.table: table for table in sample("a", "b").tables}
    tables["a"] = tables["a"].model_copy(
        update={
            "foreign_keys": (key("ab", "b"), key("self", "a"), key("missing", "absent")),
        }
    )
    tables["b"] = tables["b"].model_copy(update={"foreign_keys": (key("ba", "a"),)})
    graph = resolve_dependencies(Selection(("a",), tables, {"a": 1, "b": 1}, frozenset()), 0)
    assert {issue.code for issue in graph.issues} == {
        "DEPENDENCY_CYCLE",
        "MISSING_PARENT",
        "SELF_REFERENCE",
    }


def test_reused_parents_are_terminal_and_always_null_avoids_expansion() -> None:
    tables = {table.id.table: table for table in sample("parent", "child").tables}
    columns = tuple(
        ColumnSchema(
            name=name,
            ordinal=index,
            type=ColumnType(name="integer", supported=True),
            nullable=True,
            default_kind="none",
        )
        for index, name in enumerate(("first", "second"), 1)
    )
    tables["child"] = tables["child"].model_copy(
        update={
            "columns": columns,
            "foreign_keys": (key("fk", "parent"),),
        }
    )
    tables["parent"] = tables["parent"].model_copy(update={"foreign_keys": (key("missing", "x"),)})
    selection = Selection(("child",), tables, {"parent": 0, "child": 2}, frozenset({"parent"}))
    graph = resolve_dependencies(selection, 0)
    assert graph.order == ("parent", "child")
    assert graph.dependencies["child"][0].source == "existing"
    assert not graph.issues
    graph = resolve_dependencies(selection, 1)
    assert graph.order == ("child",)
    assert graph.dependencies["child"][0].source == "null"
