"""Build a read-only generation plan from normalized schema metadata."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from seed.bindings import Binding, choose_binding
from seed.config import SeedConfig, load_config
from seed.dependencies import Dependency, KeySource, resolve_dependencies
from seed.inspection import read_schema, requested_tables
from seed.metadata import DatabaseSchema, ForeignKey, Metadata, TableId, TableSchema, Target
from seed.selection import MAX_ROWS, resolve_selection, validate_row_override

type Mode = Literal["live", "offline"]
_MODES: tuple[Mode, ...] = ("live", "offline")


class PlanIssue(Metadata):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    table: TableId | None = None
    column: str | None = None
    constraint: str | None = None
    ordinal: int | None = None


class Compatibility(Metadata):
    executable: bool
    issues: tuple[PlanIssue, ...]


class PlanSettings(Metadata):
    locale: str
    random_seed: int
    reference_time: datetime
    batch_size: int
    null_rate: float


class PlannedDependency(Metadata):
    foreign_key: ForeignKey
    source: KeySource


class PlannedTable(Metadata):
    id: TableId
    requested: bool
    rows: int
    parents: tuple[TableId, ...]
    dependencies: tuple[PlannedDependency, ...]
    key_source: KeySource
    bindings: dict[Mode, tuple[Binding, ...]]


class GenerationPlan(Metadata):
    target: Target
    schema_fingerprint: str
    settings: PlanSettings
    total_rows: int
    tables: tuple[PlannedTable, ...]
    compatibility: dict[Mode, Compatibility]

    @property
    def executable(self) -> bool:
        """Return whether at least one execution mode has a feasible plan."""
        return any(mode.executable for mode in self.compatibility.values())


def plan_database(
    path: Path,
    *,
    schema: str | None,
    filters: list[str],
    rows: int | None,
    locale: str | None,
    random_seed: int | None,
) -> GenerationPlan:
    """Read a schema snapshot and build a plan without reading table data."""
    validate_row_override(filters, rows)
    config = load_config(path, schema=schema, locale=locale, random_seed=random_seed)
    requested_tables(config.database.schema_name, filters)
    metadata = read_schema(config, config.database.schema_name)
    return build_plan(config, metadata, filters, rows)


def build_plan(
    config: SeedConfig,
    schema: DatabaseSchema,
    filters: list[str],
    rows: int | None = None,
) -> GenerationPlan:
    """Resolve plan compatibility and bindings for live and offline execution."""
    selection = resolve_selection(config, schema, filters, rows)
    graph = resolve_dependencies(selection, config.generation.null_rate)
    total = sum(selection.counts[name] for name in graph.order)
    common = [
        PlanIssue(
            code=issue.code,
            message=issue.message,
            table=selection.tables[issue.table].id,
            constraint=issue.constraint,
        )
        for issue in graph.issues
    ]
    if total > MAX_ROWS:
        common.append(PlanIssue(code="ROW_LIMIT_EXCEEDED", message="The plan exceeds 100000 rows."))
    if not graph.order:
        common.append(
            PlanIssue(
                code="NO_TABLES", severity="warning", message="No ordinary tables were selected."
            )
        )
    issues: dict[Mode, list[PlanIssue]] = {mode: list(common) for mode in _MODES}
    planned: list[PlannedTable] = []
    for name in graph.order:
        table = selection.tables[name]
        count = selection.counts[name]
        dependencies = graph.dependencies[name]
        parents = {
            dependency.key.parent for dependency in dependencies if dependency.source != "null"
        }
        if count:
            bindings = _bindings(config, table, count, dependencies, issues)
            source: KeySource = "generated"
        else:
            bindings = {mode: () for mode in _MODES}
            source = "existing" if name in selection.reuse_existing else "none"
            if source == "existing" and any(
                code in {"ROW_LEVEL_SECURITY", "UNSUPPORTED_RELATION_KIND"} for code in table.issues
            ):
                issues["live"].append(
                    PlanIssue(
                        code="UNSUPPORTED_EXISTING_PARENT",
                        table=table.id,
                        message="This relation cannot be used as an existing parent.",
                    )
                )
        planned.append(
            PlannedTable(
                id=table.id,
                requested=name in selection.requested,
                rows=count,
                parents=tuple(sorted(parents, key=lambda item: (item.schema_name, item.table))),
                dependencies=tuple(
                    PlannedDependency(foreign_key=dependency.key, source=dependency.source)
                    for dependency in dependencies
                ),
                key_source=source,
                bindings=bindings,
            )
        )
    settings = config.generation
    return GenerationPlan(
        target=schema.target,
        schema_fingerprint=schema.fingerprint,
        total_rows=total,
        settings=PlanSettings(
            locale=settings.locale,
            random_seed=settings.random_seed,
            reference_time=settings.reference_time,
            batch_size=settings.batch_size,
            null_rate=settings.null_rate,
        ),
        tables=tuple(planned),
        compatibility={
            mode: Compatibility(
                executable=not any(issue.severity == "error" for issue in issues[mode]),
                issues=tuple(issues[mode]),
            )
            for mode in _MODES
        },
    )


def _bindings(
    config: SeedConfig,
    table: TableSchema,
    rows: int,
    dependencies: tuple[Dependency, ...],
    issues: dict[Mode, list[PlanIssue]],
) -> dict[Mode, tuple[Binding, ...]]:
    def blocked(
        code: str,
        message: str,
        column: str | None = None,
        modes: tuple[Mode, ...] = _MODES,
    ) -> None:
        issue = PlanIssue(code=code, message=message, table=table.id, column=column)
        for mode in modes:
            issues[mode].append(issue)

    for code in table.issues:
        if code != "UNSUPPORTED_FOREIGN_KEY":
            blocked(code, "A reflected feature is outside the supported generation subset.")
    rules = config.rules.get(table.id.table, {})
    for unknown in sorted(rules.keys() - {column.name for column in table.columns}):
        blocked("UNKNOWN_RULE_COLUMN", "A generator rule refers to an unknown column.")

    sources = {column: edge for edge in dependencies for column in edge.key.columns}
    managed = {column for key in table.foreign_keys for column in key.columns}
    for edge in dependencies:
        if edge.source == "existing":
            blocked(
                "EXISTING_PARENT_OFFLINE",
                "An existing parent key source is available only live.",
                modes=("offline",),
            )
            issues["live"].append(
                PlanIssue(
                    code="EXISTING_PARENT_UNVERIFIED",
                    severity="warning",
                    table=table.id,
                    constraint=edge.key.name,
                    message="Existing parent keys require live validation.",
                )
            )

    live, offline = [], []
    for column in table.columns:
        name = column.name
        rule = rules.get(name)
        server_key = column.default_kind in {"identity", "owned_serial"}
        generated = column.generated is not None
        if rule is not None and (name in managed or generated or server_key):
            blocked("MANAGED_COLUMN_RULE", "A managed column cannot have a generator rule.", name)
        if generated:
            choice = Binding(column=name, source="omit")
        elif name in managed:
            managed_edge = sources.get(name)
            choice = Binding(
                column=name,
                source="null" if managed_edge and managed_edge.source == "null" else "foreign_key",
                foreign_key=managed_edge.key.name if managed_edge else None,
            )
            if server_key:
                blocked(
                    "MANAGED_KEY_CONFLICT", "A foreign key cannot also allocate an identity.", name
                )
        elif server_key:
            live.append(Binding(column=name, source="server_identity"))
            offline.append(Binding(column=name, source="explicit_identity", generator="integer"))
            if (
                column.sequence_max is None
                or rows > column.sequence_max
                or not any(
                    feature.name == f"sequence {name}" and feature.reason == "SERVER_ALLOCATED_KEY"
                    for feature in table.features
                )
            ):
                blocked(
                    "UNSUPPORTED_OFFLINE_SEQUENCE",
                    "The sequence cannot allocate the offline IDs.",
                    name,
                    ("offline",),
                )
            continue
        else:
            bounds = tuple(
                bound for check in table.checks for bound in check.bounds if bound.column == name
            )
            choice, compatible = choose_binding(column, rule, config.generation.locale, bounds)
            if not compatible:
                blocked(
                    "INCOMPATIBLE_BINDING", "The planned generator cannot satisfy the column.", name
                )
        live.append(choice)
        offline.append(choice)
    if not any(binding.source != "omit" for binding in offline):
        blocked(
            "NO_OFFLINE_COLUMNS", "An offline table needs an output column.", modes=("offline",)
        )
    return {"live": tuple(live), "offline": tuple(offline)}
