"""Scalar domains and exact temporal precision."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from test_planning import column
from test_streaming import SETTINGS, TABLE

from seed.config import GeneratorRule
from seed.metadata import ColumnType, NumericBound
from seed.scalars import scalar_value
from seed.streaming import RunContext


def test_decimal_open_bounds_and_scale_are_exact() -> None:
    price = column("price", "numeric").model_copy(
        update={"type": ColumnType(name="numeric", supported=True, precision=4, scale=2)}
    )
    bounds = (
        NumericBound(column="price", operator=">", value="1.00"),
        NumericBound(column="price", operator="<", value="1.02"),
    )
    result = scalar_value(RunContext(SETTINGS, TABLE), price, "decimal", None, bounds)
    assert isinstance(result, Decimal)
    assert result == Decimal("1.01") and result.as_tuple().exponent == -2


def test_generic_scalars_and_nullable_override() -> None:
    ctx = RunContext(SETTINGS, TABLE)
    assert type(scalar_value(ctx, column("active", "boolean"), "boolean", None)) is bool
    assert isinstance(scalar_value(ctx, column("ref", "uuid"), "uuid", None), UUID)
    assert type(scalar_value(ctx, column("count"), "integer", None)) is int
    nullable = column("count").model_copy(update={"nullable": True})
    assert scalar_value(ctx, nullable, "integer", GeneratorRule(null_rate=1)) is None
    text = column("short", "varchar").model_copy(
        update={"type": ColumnType(name="varchar", supported=True, length=2)}
    )
    assert len(str(scalar_value(ctx, text, "text", None))) == 2
    enum = column("state", "enum").model_copy(
        update={"type": ColumnType(name="enum", supported=True, enum_labels=("new", "ready"))}
    )
    assert scalar_value(ctx, enum, "choice", None) in {"new", "ready"}


def test_temporal_window_and_declared_timestamp_precision() -> None:
    ctx = RunContext(SETTINGS, TABLE)
    for aware in (True, False):
        item = column("created", "timestamp").model_copy(
            update={
                "type": ColumnType(name="timestamp", supported=True, precision=2, timezone=aware)
            }
        )
        stamp = scalar_value(ctx, item, "datetime", None)
        assert isinstance(stamp, datetime) and stamp.microsecond % 10_000 == 0
        assert (stamp.tzinfo is UTC) == aware
        latest = SETTINGS.reference_time
        assert latest - timedelta(days=365) <= stamp.replace(tzinfo=UTC) <= latest
    day = scalar_value(ctx, column("day", "date"), "date", None)
    assert type(day) is date
    assert (
        SETTINGS.reference_time.date() - timedelta(days=365)
        <= day
        <= SETTINGS.reference_time.date()
    )
