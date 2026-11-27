"""Deterministic record and batching primitives for generation runs."""

import hashlib
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from random import Random
from uuid import UUID

from faker import Faker

from seed.metadata import TableId
from seed.planning.plan import PlanIssue, PlanSettings

type Value = None | bool | int | str | Decimal | date | datetime | UUID
type RecordBatch = tuple[GeneratedRecord, ...]
MAX_BATCH = 10_000
MAX_ATTEMPTS = 100
_ALGORITHM = "seed-offline-v1"


@dataclass(frozen=True)
class GeneratedRecord:
    """A record with a stable table-local ordinal and insertion-ordered columns."""

    table: TableId
    ordinal: int
    values: dict[str, Value] = field(repr=False)


class GenerationError(Exception):
    """A scoped failure without candidate values."""

    def __init__(self, issue: PlanIssue) -> None:
        super().__init__(issue.message)
        self.issue = issue


class RunContext:
    """Keep each binding's independent RNG and Faker stream local to the run."""

    def __init__(self, settings: PlanSettings, table: TableId) -> None:
        self.settings = settings
        self.table = table
        self._streams: dict[tuple[str, str], Random] = {}
        self._providers: dict[str, Faker] = {}

    def _seed(self, binding: str, purpose: str) -> int:
        encoded = json.dumps(
            [
                _ALGORITHM,
                self.settings.random_seed,
                self.table.schema_name,
                self.table.table,
                binding,
                purpose,
            ],
            separators=(",", ":"),
        ).encode("utf-8")
        return int.from_bytes(hashlib.sha256(encoded).digest(), "big")

    def random(self, binding: str, purpose: str = "scalar") -> Random:
        """Return the stable stream for one binding and purpose."""
        key = (binding, purpose)
        stream = self._streams.get(key)
        if stream is None:
            stream = Random(self._seed(binding, purpose))
            self._streams[key] = stream
        return stream

    def faker(self, binding: str) -> Faker:
        """Return a seeded Faker instance without changing global RNG state."""
        provider = self._providers.get(binding)
        if provider is None:
            provider = Faker(self.settings.locale)
            provider.seed_instance(self._seed(binding, "faker"))
            self._providers[binding] = provider
        return provider


def validate_batch_size(size: int) -> None:
    """Check the batch bound independently of record availability."""
    if not 1 <= size <= MAX_BATCH:
        raise GenerationError(
            PlanIssue(code="INVALID_BATCH_SIZE", message="Batch size must be from 1 to 10000.")
        )


def batches(records: Iterable[GeneratedRecord], size: int) -> Iterator[RecordBatch]:
    """Yield nonempty bounded batches containing records from one table."""
    validate_batch_size(size)
    pending: list[GeneratedRecord] = []
    for record in records:
        if pending and record.table != pending[0].table:
            yield tuple(pending)
            pending.clear()
        pending.append(record)
        if len(pending) == size:
            yield tuple(pending)
            pending.clear()
    if pending:
        yield tuple(pending)


def retry_row(
    table: TableId,
    ordinal: int,
    attempt: Callable[[], GeneratedRecord | None],
) -> GeneratedRecord:
    """Stop after a bounded number of attempts to accept a row."""
    for _ in range(MAX_ATTEMPTS):
        record = attempt()
        if record is not None:
            return record
    raise GenerationError(
        PlanIssue(
            code="RETRY_EXHAUSTED",
            message="Could not generate a valid record within 100 attempts.",
            table=table,
            ordinal=ordinal,
        )
    )
