"""Preview trims leaf generation while retaining the complete parent pool."""

from collections.abc import Iterator

import pytest
from test_generation import BASE, foreign_key
from test_planning import column
from test_selection import sample

from seed.config import SeedConfig, parse_config
from seed.generation import generate_batches
from seed.metadata import DatabaseSchema
from seed.planning import GenerationPlan, build_plan
from seed.preview import sample_tables
from seed.streaming import RecordBatch


def test_preview_generates_full_parent_pool_and_only_requested_leaf_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = sample("child", "parent")
    child, parent = schema.tables
    parent = parent.model_copy(update={"columns": (column("id"),)})
    child = child.model_copy(
        update={
            "columns": (column("parent_id"),),
            "foreign_keys": (foreign_key(parent, ("parent_id",), ("id",)),),
        }
    )
    schema = schema.model_copy(update={"tables": (child, parent)})
    config = parse_config(BASE + "[tables.child]\nrows=80\n[tables.parent]\nrows=40\n")
    original = build_plan(config, schema, ["child"])
    generated = []

    def traced(
        plan: GenerationPlan,
        model: DatabaseSchema,
        settings: SeedConfig,
    ) -> Iterator[RecordBatch]:
        for batch in generate_batches(plan, model, settings):
            generated.append((batch[0].table.table, len(batch)))
            yield batch

    monkeypatch.setattr("seed.preview.generate_batches", traced)
    (child_sample,) = sample_tables(original, schema, config, 3)
    assert child_sample.table.table == "child" and len(child_sample.rows) == 3
    assert generated == [("parent", 40), ("child", 3)]
    assert original.total_rows == 120
