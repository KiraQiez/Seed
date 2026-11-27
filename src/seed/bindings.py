"""Choose and validate planned generators without producing values."""

from datetime import date, datetime
from decimal import Decimal, DecimalException
from uuid import UUID

from seed.config import GeneratorRule, Scalar
from seed.metadata import ColumnSchema, Metadata, NumericBound
from seed.numeric import INTEGER_BITS, numeric_grid

_GENERIC = {
    **dict.fromkeys(INTEGER_BITS, "integer"),
    "numeric": "decimal",
    "text": "text",
    "varchar": "text",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "datetime",
    "uuid": "uuid",
    "enum": "choice",
}
_SEMANTIC = {
    **dict.fromkeys(("email", "email_address"), "email"),
    **dict.fromkeys(("phone", "phone_number"), "phone"),
    **{
        name: name
        for name in ("first_name", "last_name", "name", "address", "city", "country", "description")
    },
}
_TEXT_GENERATORS = frozenset(_SEMANTIC.values()) | {"text"}


class Binding(Metadata):
    column: str
    source: str
    generator: str | None = None
    foreign_key: str | None = None
    explicit: bool = False


def choose_binding(
    column: ColumnSchema,
    rule: GeneratorRule | None,
    locale: str,
    bounds: tuple[NumericBound, ...],
) -> tuple[Binding, bool]:
    """Select a generator and report whether its bindings fit the reflected schema."""
    kind = column.type
    generic = _GENERIC.get(kind.name)
    inferred = _SEMANTIC.get(column.name.lower()) if generic == "text" else None
    if inferred == "phone" and locale != "en_US":
        inferred = None
    if inferred == "email" and kind.length is not None and kind.length < 13:
        inferred = None
    explicit = rule.generator if rule else None
    generator = explicit or inferred or generic
    binding = Binding(
        column=column.name, source="generator", generator=generator, explicit=rule is not None
    )
    if not kind.supported or not generator or not generic:
        return binding, False
    if rule and rule.null_rate and not column.nullable:
        return binding, False
    if explicit == "phone" and locale != "en_US":
        return binding, False
    if explicit == "email" and kind.length is not None and kind.length < 13:
        return binding, False
    if explicit in {"choice", "constant"}:
        assert rule is not None
        values = rule.values if rule.values is not None else [rule.value]
        valid_values = all(
            value is not None and _compatible_value(value, column, bounds) for value in values
        )
        if valid_values and kind.name == "numeric":
            normalized = {Decimal(value) for value in values if isinstance(value, (int, str))}
            valid_values = len(normalized) == len(values)
        return binding, valid_values
    if generator != generic and not (generic == "text" and generator in _TEXT_GENERATORS):
        return binding, False
    if generic == "choice" and not kind.enum_labels:
        return binding, False
    if generic in {"integer", "decimal"}:
        return binding, _feasible_numeric(column, rule, bounds)
    return binding, True


def _compatible_value(
    value: Scalar, column: ColumnSchema, bounds: tuple[NumericBound, ...]
) -> bool:
    kind = column.type
    if kind.name in INTEGER_BITS:
        return type(value) is int and _feasible_numeric(column, None, bounds, Decimal(value))
    if kind.name == "numeric":
        if not isinstance(value, str) and type(value) is not int:
            return False
        try:
            return _feasible_numeric(column, None, bounds, Decimal(value))
        except DecimalException:
            return False
    if kind.name in {"text", "varchar", "enum"}:
        return (
            isinstance(value, str)
            and "\x00" not in value
            and (kind.length is None or len(value) <= kind.length)
            and (kind.name != "enum" or value in kind.enum_labels)
        )
    if kind.name == "uuid" and isinstance(value, str):
        try:
            return str(UUID(value)) == value
        except ValueError:
            return False
    if kind.name == "boolean":
        return type(value) is bool
    if kind.name == "date":
        return type(value) is date
    if kind.name == "timestamp" and isinstance(value, datetime):
        return (value.utcoffset() is not None) == bool(kind.timezone)
    return False


def _feasible_numeric(
    column: ColumnSchema,
    rule: GeneratorRule | None,
    bounds: tuple[NumericBound, ...],
    value: Decimal | None = None,
) -> bool:
    return numeric_grid(column, rule, bounds, value) is not None
