"""Distinguish successful batches from failed candidate generation."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from test_planning import column
from test_selection import sample

from seed.config import SeedConfig
from seed.metadata import DatabaseSchema
from seed.planning import GenerationPlan, PlanIssue, PlanRequest, build_plan
from seed.streaming import GeneratedRecord, GenerationError, RecordBatch
from seed.validation import validate


def test_dataset_failure_keeps_prior_batch_count_and_scoped_ordinal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "seed.toml"
    config.write_text('version=1\n[database]\nurl_env="SEED_TEST_URL"\n', encoding="utf-8")
    monkeypatch.setenv("SEED_TEST_URL", "postgresql://test:private-password@127.0.0.1/test")
    schema = sample("items")
    table = schema.tables[0].model_copy(update={"columns": (column("id"),)})
    schema = schema.model_copy(update={"tables": (table,)})

    def snapshot(
        request: PlanRequest,
        settings: SeedConfig,
        **kwargs: object,
    ) -> tuple[DatabaseSchema, GenerationPlan]:
        return schema, build_plan(settings, schema, request.filters, request.rows)

    def failed_batches(*args: object) -> Iterator[RecordBatch]:
        yield (GeneratedRecord(table.id, 0, {"id": 1}),)
        raise GenerationError(
            PlanIssue(
                code="RETRY_EXHAUSTED",
                message="Could not generate a valid record.",
                table=table.id,
                ordinal=1,
            )
        )

    monkeypatch.setattr(PlanRequest, "snapshot", snapshot)
    monkeypatch.setattr("seed.validation.generate_batches", failed_batches)
    report = validate(PlanRequest(config, None, ["items"], 3, None, None), dataset=True)
    assert report.status == 4 and report.dataset.status == "failed"
    assert report.dataset.rows_checked == 1
    assert report.issues() == [
        {
            "code": "RETRY_EXHAUSTED",
            "severity": "error",
            "message": "Could not generate a valid record.",
            "scope": {
                "mode": "offline",
                "table": {"schema": "Seed.Scope", "table": "items"},
                "ordinal": 1,
            },
        }
    ]
    assert "private-password" not in repr(report.payload())
