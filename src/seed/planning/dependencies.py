"""Expand required parents and order the generation graph."""

import heapq
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from seed.metadata import ForeignKey
from seed.planning.selection import Selection

type KeySource = Literal["generated", "existing", "none", "null"]


@dataclass(frozen=True)
class Dependency:
    key: ForeignKey
    source: KeySource


@dataclass(frozen=True)
class GraphIssue:
    table: str
    code: str
    message: str
    constraint: str | None = None


@dataclass(frozen=True)
class DependencyGraph:
    order: tuple[str, ...]
    dependencies: dict[str, tuple[Dependency, ...]]
    issues: tuple[GraphIssue, ...]


def resolve_dependencies(selection: Selection, null_rate: float) -> DependencyGraph:
    """Expand the reachable graph without reading any database rows."""
    pending = list(selection.requested)
    heapq.heapify(pending)
    edges: dict[str, tuple[Dependency, ...]] = {}
    issues: list[GraphIssue] = []
    while pending:
        name = heapq.heappop(pending)
        if name in edges:
            continue
        table = selection.tables[name]
        dependencies: list[Dependency] = []
        if selection.counts[name]:
            nullable = {column.name for column in table.columns if column.nullable}
            unsupported = {
                feature.name
                for feature in table.features
                if feature.reason == "UNSUPPORTED_FOREIGN_KEY"
            }
            for key in table.foreign_keys:
                parent = key.parent.table
                if key.parent == table.id:
                    code, message = (
                        "SELF_REFERENCE",
                        "Self-referencing foreign keys are unsupported.",
                    )
                elif (
                    key.parent.schema_name != table.id.schema_name
                    or f"foreign key {key.name}" in unsupported
                    or key.validated is not True
                    or key.enforced is not True
                    or key.deferrable
                    or key.match != "SIMPLE"
                ):
                    code, message = "UNSUPPORTED_FOREIGN_KEY", "A foreign key is unsupported."
                elif parent not in selection.tables:
                    code, message = "MISSING_PARENT", "A foreign key parent could not be inspected."
                else:
                    source: KeySource = "none"
                    if null_rate == 1 and key.columns and nullable.issuperset(key.columns):
                        source = "null"
                    elif selection.counts[parent]:
                        source = "generated"
                    elif parent in selection.reuse_existing:
                        source = "existing"
                    dependencies.append(Dependency(key, source))
                    if source != "null":
                        heapq.heappush(pending, parent)
                    if source != "none":
                        continue
                    code, message = (
                        "EMPTY_PARENT",
                        "A foreign key has no planned parent key source.",
                    )
                issues.append(GraphIssue(name, code, message, key.name))
        edges[name] = tuple(dependencies)

    order, unresolved = _parent_first(edges)
    if unresolved:
        issues.append(
            GraphIssue(
                unresolved[0],
                "DEPENDENCY_CYCLE",
                "A dependency cycle prevents ordering every reachable table.",
            )
        )
    return DependencyGraph(tuple(order + unresolved), edges, tuple(issues))


def _parent_first(edges: dict[str, tuple[Dependency, ...]]) -> tuple[list[str], list[str]]:
    parents = {
        name: {edge.key.parent.table for edge in dependencies if edge.source != "null"}
        for name, dependencies in edges.items()
    }
    children: dict[str, set[str]] = defaultdict(set)
    for name, requirements in parents.items():
        for parent in requirements:
            children[parent].add(name)
    ready = [name for name, requirements in parents.items() if not requirements]
    heapq.heapify(ready)
    ordered = []
    while ready:
        ready_name = heapq.heappop(ready)
        ordered.append(ready_name)
        for child in children[ready_name]:
            parents[child].remove(ready_name)
            if not parents[child]:
                heapq.heappush(ready, child)
    return ordered, sorted(set(edges) - set(ordered))
