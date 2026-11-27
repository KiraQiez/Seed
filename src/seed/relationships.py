"""Retain and consume only the parent keys required by the offline plan."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from seed.metadata import TableId, TableSchema
from seed.planning import GenerationPlan, PlanIssue, PlannedDependency, PlannedTable
from seed.streaming import GeneratedRecord, GenerationError, RunContext, Value

type KeyTuple = tuple[Value, ...]
type PoolId = tuple[TableId, tuple[str, ...]]


def _pool_id(edge: PlannedDependency) -> PoolId:
    return edge.foreign_key.parent, edge.foreign_key.parent_columns


@dataclass
class KeyPool:
    values: list[KeyTuple] = field(default_factory=list)
    members: set[KeyTuple] = field(default_factory=set)

    def add(self, values: KeyTuple) -> None:
        if None not in values and values not in self.members:
            self.values.append(values)
            self.members.add(values)


class ParentPools:
    """Own generated key tuples for an entire run."""

    def __init__(self, plan: GenerationPlan) -> None:
        self._remaining = Counter(
            _pool_id(edge)
            for table in plan.tables
            if table.rows
            for edge in table.dependencies
            if edge.source == "generated"
        )
        self._retained: dict[TableId, dict[tuple[str, ...], KeyPool]] = defaultdict(dict)
        for table, columns in self._remaining:
            self._retained[table][columns] = KeyPool()

    def accept(self, record: GeneratedRecord) -> None:
        """Register the accepted record's non-null referenced tuples."""
        for columns, pool in self._retained.get(record.table, {}).items():
            pool.add(tuple(record.values.get(column) for column in columns))

    def for_edge(self, edge: PlannedDependency) -> KeyPool:
        table, columns = _pool_id(edge)
        return self._retained[table][columns]

    def finish(self, table: PlannedTable) -> None:
        """Release pools whose last consumer has finished."""
        for edge in table.dependencies:
            if edge.source == "generated":
                key = _pool_id(edge)
                self._remaining[key] -= 1
                if self._remaining[key] == 0:
                    del self._retained[key[0]][key[1]]
                    del self._remaining[key]


@dataclass
class _Available:
    values: list[KeyTuple]
    positions: dict[KeyTuple, int]

    @classmethod
    def from_pool(cls, pool: KeyPool) -> "_Available":
        return cls(list(pool.values), {value: index for index, value in enumerate(pool.values)})

    def take(self, key: KeyTuple) -> None:
        index = self.positions.pop(key)
        last = self.values.pop()
        if index < len(self.values):
            self.values[index] = last
            self.positions[last] = index


@dataclass
class ForeignKeys:
    """Draw complete tuples and reserve one-to-one keys only after row acceptance."""

    context: RunContext
    dependencies: tuple[PlannedDependency, ...]
    nullable: frozenset[str]
    pools: ParentPools
    available: dict[str, _Available] = field(default_factory=dict)

    @classmethod
    def prepare(
        cls,
        table: PlannedTable,
        metadata: TableSchema,
        pools: ParentPools,
        context: RunContext,
    ) -> "ForeignKeys":
        nullable = frozenset(column.name for column in metadata.columns if column.nullable)
        state = cls(context, table.dependencies, nullable, pools)
        unique_keys: dict[frozenset[str], bool] = {}
        for unique_key in metadata.unique_keys:
            if unique_key.supported is True:
                columns = frozenset(unique_key.columns)
                unique_keys[columns] = unique_keys.get(columns, True) and bool(
                    unique_key.nulls_distinct
                )
        if metadata.primary_key:
            unique_keys[frozenset(metadata.primary_key.columns)] = False
        for edge in table.dependencies:
            key = edge.foreign_key
            if edge.source == "null":
                continue
            if edge.source != "generated":
                raise state._error(key.name, "No offline parent key source is available.")
            pool = pools.for_edge(edge)
            if not pool.values:
                raise state._error(key.name, "The generated parent key pool is empty.")
            columns = frozenset(key.columns)
            if columns in unique_keys:
                null_allowed = state._allows_null(edge)
                if not (null_allowed and unique_keys[columns]):
                    capacity = len(pool.values) + int(null_allowed)
                    if table.rows > capacity:
                        raise state._error(
                            key.name, "The unique foreign key capacity is exhausted."
                        )
                state.available[key.name] = _Available.from_pool(pool)
        return state

    def _allows_null(self, edge: PlannedDependency) -> bool:
        return bool(self.context.settings.null_rate) and self.nullable.issuperset(
            edge.foreign_key.columns
        )

    def draw(self) -> dict[str, Value] | None:
        """Draw candidate foreign key values; return None on depleted non-null keys."""
        result: dict[str, Value] = {}
        for edge in self.dependencies:
            foreign = edge.foreign_key
            rng = self.context.random(foreign.name, "foreign_key")
            if edge.source == "null" or (
                self._allows_null(edge) and rng.random() < self.context.settings.null_rate
            ):
                result.update(dict.fromkeys(foreign.columns))
                continue
            unique = self.available.get(foreign.name)
            values = unique.values if unique is not None else self.pools.for_edge(edge).values
            if not values:
                return None
            result.update(zip(foreign.columns, rng.choice(values), strict=True))
        return result

    def contains(self, values: dict[str, Value]) -> bool:
        """Check the generated tuples against their parent pools."""
        for edge in self.dependencies:
            key = tuple(values[column] for column in edge.foreign_key.columns)
            if all(value is None for value in key):
                if edge.source != "null" and not self._allows_null(edge):
                    return False
            elif edge.source != "generated" or key not in self.pools.for_edge(edge).members:
                return False
        return True

    def accept(self, values: dict[str, Value]) -> None:
        for edge in self.dependencies:
            available = self.available.get(edge.foreign_key.name)
            if available is not None:
                key = tuple(values[column] for column in edge.foreign_key.columns)
                if None not in key:
                    available.take(key)

    def _error(self, constraint: str, message: str) -> GenerationError:
        return GenerationError(
            PlanIssue(
                code="PARENT_KEYS_EXHAUSTED",
                message=message,
                constraint=constraint,
                table=self.context.table,
            )
        )
