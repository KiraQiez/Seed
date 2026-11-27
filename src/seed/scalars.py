"""Generate typed scalar values from executable column bindings."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import Random
from string import ascii_lowercase, digits
from uuid import UUID

from seed.config import GeneratorRule, Scalar
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
    if rule and rule.generator == "constant" and rule.value is not None:
        return _configured_value(rule.value, column)
    if rule and rule.generator == "choice" and rule.values:
        return _configured_value(rng.choice(rule.values), column)
    if generator == "email":
        suffix = "@example.com"
        width = min(16, kind.length - len(suffix)) if kind.length is not None else 16
        if width > 0:
            return random_text(rng, width) + suffix
    if generator == "phone":
        if context.settings.locale == "en_US" and (kind.length is None or kind.length >= 15):
            return f"+1-202-555-01{rng.randrange(100):02}"
    if generator in {
        "first_name",
        "last_name",
        "name",
        "address",
        "city",
        "country",
        "description",
    }:
        provider = context.faker(name)
        value = (
            provider.text() if generator == "description" else str(getattr(provider, generator)())
        )
        return value[: kind.length] if kind.length is not None else value
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


def _configured_value(value: Scalar, column: ColumnSchema) -> Value:
    """Convert a validated config literal to the matching database scalar."""
    if column.type.name == "numeric" and isinstance(value, (int, str)):
        number = Decimal(value)
        grid = numeric_grid(column, None, (), number)
        if grid is not None and column.type.scale is not None:
            return grid.decimal(grid.first)
        return number
    if column.type.name == "uuid" and isinstance(value, str):
        return UUID(value)
    if isinstance(value, datetime) and value.utcoffset() is not None:
        return value.astimezone(UTC)
    return value
