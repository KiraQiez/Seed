"""Generation stream reproducibility and bounds."""

import random
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from seed.generation.streaming import (
    MAX_ATTEMPTS,
    GeneratedRecord,
    GenerationError,
    RunContext,
    batches,
    retry_row,
)
from seed.metadata import TableId
from seed.planning.plan import PlanSettings

TABLE = TableId(schema="test", table="items")
SETTINGS = PlanSettings(
    locale="en_US",
    random_seed=123,
    reference_time=datetime(2025, 1, 1, tzinfo=UTC),
    batch_size=4,
    null_rate=0,
)


def run(size: int) -> list[GeneratedRecord]:
    context = RunContext(SETTINGS, TABLE)
    records = (
        GeneratedRecord(
            TABLE,
            index,
            {
                "number": context.random("number").randrange(1000),
                "name": context.faker("name").first_name(),
            },
        )
        for index in range(10)
    )
    chunks = list(batches(records, size))
    assert all(0 < len(chunk) <= size for chunk in chunks)
    return [record for chunk in chunks for record in chunk]


def test_batches_and_parallel_runs_preserve_draw_order() -> None:
    before = random.getstate()
    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(run, [1, 7])
    assert first == second == run(4)
    assert random.getstate() == before


def test_batches_never_cross_tables() -> None:
    other = TableId(schema="test", table="other")
    chunks = list(batches([GeneratedRecord(TABLE, 0, {}), GeneratedRecord(other, 0, {})], 10))
    assert [chunk[0].table for chunk in chunks] == [TABLE, other]


def test_retry_cap_and_scoped_failure() -> None:
    calls = 0

    def rejected() -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(GenerationError) as error:
        retry_row(TABLE, 12, rejected)
    assert calls == MAX_ATTEMPTS
    assert error.value.issue.code == "RETRY_EXHAUSTED"
    assert error.value.issue.table == TABLE and error.value.issue.ordinal == 12
