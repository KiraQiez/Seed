"""Validate candidate values and reserve uniqueness only for accepted rows."""

from dataclasses import dataclass, field
from decimal import Decimal
from math import prod
from uuid import UUID

from seed.config import GeneratorRule, Scalar
from seed.generation.relationships import KeyTuple
from seed.generation.streaming import GenerationError, Value
from seed.metadata import ColumnSchema, NumericBound, TableId, TableSchema
from seed.planning.bindings import compatible_value
from seed.planning.numeric import numeric_grid
from seed.planning.plan import PlanIssue


@dataclass(frozen=True)
class UniqueRule:
    name: str
    columns: tuple[str, ...]
    nulls_distinct: bool


@dataclass(frozen=True)
class Domain:
    """An upper bound on non-null candidates and whether null can be emitted."""

    capacity: int | None
    nullable: bool


def value_matches(
    value: Value,
    column: ColumnSchema,
    bounds: tuple[NumericBound, ...],
    rule: GeneratorRule | None,
) -> bool:
    """Check the typed value and configured numeric interval."""
    if value is None:
        return column.nullable
    kind = column.type.name
    converted: Scalar
    if isinstance(value, Decimal):
        if kind != "numeric" or not value.is_finite():
            return False
        converted = str(value)
    elif isinstance(value, UUID):
        if kind != "uuid":
            return False
        converted = str(value)
    else:
        if kind in {"numeric", "uuid"}:
            return False
        converted = value
    if not compatible_value(converted, column, bounds):
        return False
    if rule and (rule.min is not None or rule.max is not None):
        number = Decimal(str(value))
        return not (
            (rule.min is not None and number < Decimal(rule.min))
            or (rule.max is not None and number > Decimal(rule.max))
        )
    return True


def scalar_domain(
    column: ColumnSchema,
    source: str,
    generator: str | None,
    rule: GeneratorRule | None,
    bounds: tuple[NumericBound, ...],
    null_rate: float,
    rows: int,
) -> Domain:
    """Bound common finite generator domains for early exhaustion checks."""
    if source == "explicit_identity":
        return Domain(rows, False)
    if source == "null":
        return Domain(0, True)
    if source != "generator":
        return Domain(None, column.nullable)
    if rule and rule.null_rate is not None:
        null_rate = rule.null_rate
    emits_null = column.nullable and null_rate > 0
    if emits_null and null_rate == 1:
        return Domain(0, True)
    capacity: int | None = None
    if rule and rule.generator in {"constant", "choice"}:
        capacity = len(rule.values) if rule.values is not None else 1
    elif generator == "choice":
        capacity = len(column.type.enum_labels)
    elif generator == "boolean":
        capacity = 2
    elif generator == "phone":
        capacity = 100
    elif generator in {"integer", "decimal"}:
        grid = numeric_grid(column, rule, bounds)
        capacity = 0 if grid is None else grid.last - grid.first + 1
    elif generator == "date":
        capacity = 366
    elif column.type.length is not None:
        width = column.type.length
        if generator == "email":
            capacity = 36 ** min(16, width - len("@example.com"))
        elif generator == "text":
            capacity = 36 ** min(24, width)
    return Domain(capacity, emits_null)


@dataclass
class UniqueReservations:
    """Record keys from accepted rows, with PostgreSQL null semantics."""

    rules: tuple[UniqueRule, ...]
    seen: tuple[set[KeyTuple], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.seen = tuple(set() for _ in self.rules)

    @classmethod
    def for_table(
        cls,
        table: TableSchema,
        configured: dict[str, GeneratorRule],
        *,
        pending: frozenset[str] = frozenset(),
    ) -> "UniqueReservations":
        rules: list[UniqueRule] = []
        if table.primary_key is not None:
            key = table.primary_key
            rules.append(UniqueRule(key.name, key.columns, False))
        rules.extend(
            UniqueRule(key.name, key.columns, bool(key.nulls_distinct))
            for key in table.unique_keys
            if key.supported is True
        )
        rules.extend(
            UniqueRule(column, (column,), True)
            for column, rule in configured.items()
            if rule.unique
        )
        return cls(tuple(rule for rule in rules if pending.isdisjoint(rule.columns)))

    def check_capacity(self, table: TableId, domains: dict[str, Domain], rows: int) -> None:
        """Refuse a finite unique domain that provably cannot satisfy the request."""
        for rule in self.rules:
            sizes: list[int] = []
            for name in rule.columns:
                domain = domains.get(name)
                if (
                    domain is None
                    or domain.capacity is None
                    or (domain.nullable and rule.nulls_distinct)
                ):
                    break
                sizes.append(min(rows, domain.capacity + int(domain.nullable)))
            else:
                if prod(sizes) < rows:
                    raise GenerationError(
                        PlanIssue(
                            code="DOMAIN_EXHAUSTED",
                            message="A unique key domain cannot satisfy the planned row count.",
                            table=table,
                            constraint=rule.name,
                        )
                    )

    def reserve(self, values: dict[str, Value]) -> bool:
        """Reserve every participating tuple together after checking for collisions."""
        candidates: list[tuple[set[KeyTuple], KeyTuple]] = []
        for rule, seen in zip(self.rules, self.seen, strict=True):
            key = tuple(values[name] for name in rule.columns)
            if rule.nulls_distinct and None in key:
                continue
            if key in seen:
                return False
            candidates.append((seen, key))
        for seen, key in candidates:
            seen.add(key)
        return True
