"""Share exact numeric domains between planning and generation."""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, DecimalException, localcontext

from seed.config import GeneratorRule
from seed.metadata import ColumnSchema, NumericBound

INTEGER_BITS = {"smallint": 16, "integer": 32, "bigint": 64}
_PG_NUMERIC_LIMIT = Decimal("1e131072")
_PG_NUMERIC_SCALE = 16_383


@dataclass(frozen=True)
class NumericGrid:
    first: int
    last: int
    scale: int

    def decimal(self, units: int) -> Decimal:
        """Convert an integer grid point without implicit context rounding."""
        number = Decimal(units)
        with localcontext() as context:
            context.prec = len(number.as_tuple().digits)
            return number.scaleb(-self.scale)


def numeric_grid(
    column: ColumnSchema,
    rule: GeneratorRule | None,
    bounds: tuple[NumericBound, ...],
    value: Decimal | None = None,
) -> NumericGrid | None:
    """Intersect schema, rule, and check constraints on a representable grid."""
    if value is not None and not value.is_finite():
        return None
    lows: list[tuple[Decimal, bool]] = []
    highs: list[tuple[Decimal, bool]] = []
    for bound in bounds:
        number = Decimal(bound.value)
        if bound.operator in {">", ">=", "="}:
            lows.append((number, bound.operator == ">"))
        if bound.operator in {"<", "<=", "="}:
            highs.append((number, bound.operator == "<"))
    if rule and rule.min is not None:
        lows.append((Decimal(rule.min), False))
    if rule and rule.max is not None:
        highs.append((Decimal(rule.max), False))
    if value is not None:
        lows.append((value, False))
        highs.append((value, False))

    kind = column.type
    scale = kind.scale
    if kind.name in INTEGER_BITS:
        limit = 2 ** (INTEGER_BITS[kind.name] - 1)
        lows.append((Decimal(-limit), False))
        highs.append((Decimal(limit - 1), False))
        scale = 0
    elif kind.precision is not None and scale is not None:
        limit_decimal = Decimal((0, (9,) * kind.precision, -scale))
        lows.append((limit_decimal.copy_negate(), False))
        highs.append((limit_decimal, False))

    lower = max(lows, default=None)
    upper = min(highs, key=lambda item: (item[0], not item[1]), default=None)
    if lower and upper and lower[0] > upper[0]:
        return None
    if scale is None:
        if lower and lower[0] >= _PG_NUMERIC_LIMIT:
            return None
        if upper and upper[0] <= _PG_NUMERIC_LIMIT.copy_negate():
            return None
        if lower and lower[0] <= _PG_NUMERIC_LIMIT.copy_negate():
            lower = (_PG_NUMERIC_LIMIT.copy_negate(), True)
        if upper and upper[0] >= _PG_NUMERIC_LIMIT:
            upper = (_PG_NUMERIC_LIMIT, True)
        # One extra decimal place permits sampling a nonempty open interval.
        scale = min(
            _PG_NUMERIC_SCALE,
            max(
                [
                    2,
                    *(
                        -int(bound[0].as_tuple().exponent) + int(bound[1])
                        for bound in (lower, upper)
                        if bound
                    ),
                ],
            ),
        )
    try:
        start = _units(lower, scale, True) if lower else None
        end = _units(upper, scale, False) if upper else None
    except DecimalException:
        return None
    if start is not None and end is not None and start > end:
        return None

    if kind.name == "numeric" and kind.scale is None:
        # Sample at most a bounded window of values near zero or the nearest bound.
        span = 1000 * 10**scale
        anchor = max(0, start) if start is not None else 0
        if end is not None:
            anchor = min(anchor, end)
        start = anchor - span if start is None else max(start, anchor - span)
        end = anchor + span if end is None else min(end, anchor + span)
    if start is None or end is None:
        return None
    return NumericGrid(start, end, scale)


def _units(bound: tuple[Decimal, bool], scale: int, lower: bool) -> int:
    value, exclusive = bound
    with localcontext() as context:
        context.prec = max(len(value.as_tuple().digits), value.adjusted() + scale + 1) + 2
        scaled = value.scaleb(scale)
        integral = scaled.to_integral_value(rounding=ROUND_CEILING if lower else ROUND_FLOOR)
        if exclusive and scaled == integral:
            integral += 1 if lower else -1
        return int(integral)
