"""Generate typed scalar values from executable column bindings."""

from datetime import UTC, timedelta
from random import Random
from string import ascii_lowercase, digits
from uuid import UUID

from seed.config import GeneratorRule
from seed.metadata import ColumnSchema, NumericBound
from seed.numeric import numeric_grid
from seed.planning import PlanIssue
from seed.streaming import GenerationError, RunContext, Value

_TEXT_ALPHABET = ascii_lowercase + digits
_MICROSECONDS_PER_DAY = 86_400_000_000


def scalar_value(
    context: RunContext,
    column: ColumnSchema,
    generator: str,
    rule: GeneratorRule | None,
    bounds: tuple[NumericBound, ...] = (),
) -> Value:
    """Draw one scalar in the binding's domain."""
    name = column.name
    null_rate = (
        rule.null_rate if rule and rule.null_rate is not None else context.settings.null_rate
    )
    if column.nullable and null_rate and context.random(name, "null").random() < null_rate:
        return None
    rng = context.random(name)
    kind = column.type
    if generator in {"integer", "decimal"}:
        grid = numeric_grid(column, rule, bounds)
        if grid is not None:
            units = rng.randint(grid.first, grid.last)
            return units if generator == "integer" else grid.decimal(units)
    elif generator == "boolean":
        return bool(rng.getrandbits(1))
    elif generator == "uuid":
        return UUID(int=rng.getrandbits(128), version=4)
    elif generator == "text":
        return random_text(rng, min(24, kind.length) if kind.length is not None else 24)
    elif generator == "choice" and kind.enum_labels:
        return rng.choice(kind.enum_labels)
    elif generator in {"date", "datetime"}:
        reference = context.settings.reference_time.astimezone(UTC)
        start = reference - timedelta(days=365)
        if generator == "date":
            return start.date() + timedelta(days=rng.randrange(366))
        precision = kind.precision if kind.precision is not None else 6
        quantum = 10 ** (6 - precision)
        offset = (-start.microsecond) % quantum
        count = (365 * _MICROSECONDS_PER_DAY - offset) // quantum
        sample = start + timedelta(microseconds=offset + rng.randint(0, count) * quantum)
        return sample if kind.timezone else sample.replace(tzinfo=None)
    raise GenerationError(
        PlanIssue(
            code="INCOMPATIBLE_BINDING",
            message="The planned generator has no compatible values.",
            table=context.table,
            column=name,
        )
    )


def random_text(rng: Random, width: int) -> str:
    """Return bounded ASCII text using the supplied private stream."""
    return "".join(rng.choices(_TEXT_ALPHABET, k=width))
