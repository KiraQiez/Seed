"""Render schema inspection metadata without executing terminal control sequences."""

from seed.metadata import DatabaseSchema


def _safe(text: str) -> str:
    return "".join(char if char.isprintable() else f"\\u{ord(char):04x}" for char in text)


def _sequence(names: tuple[str, ...]) -> str:
    return ", ".join(map(_safe, names))


def inspection_lines(report: DatabaseSchema) -> list[str]:
    """Build readable lines for the terminal schema report."""
    lines = [
        f"PostgreSQL {report.server_major} · {_safe(report.target.database)} "
        f"· schema {_safe(report.target.schema_name)}",
        f"{len(report.tables)} relations · fingerprint {report.fingerprint}",
    ]
    for table in report.tables:
        lines.append(f"{_safe(table.id.schema_name)}.{_safe(table.id.table)} ({table.kind})")
        for column in table.columns:
            kind = column.type
            modifiers: list[str] = []
            if kind.length is not None:
                modifiers.append(f"length {kind.length}")
            if kind.precision is not None:
                modifiers.append(f"precision {kind.precision}")
            if kind.scale is not None:
                modifiers.append(f"scale {kind.scale}")
            if kind.enum_labels:
                modifiers.append(f"labels {_sequence(kind.enum_labels)}")
            if kind.timezone is not None:
                modifiers.append("with time zone" if kind.timezone else "without time zone")
            details = [
                "nullable" if column.nullable else "required",
                f"default {column.default_kind}",
                *modifiers,
            ]
            if column.identity:
                details.append(f"identity {column.identity}")
            if column.generated:
                details.append(f"generated {column.generated}")
            if not kind.supported:
                details.append("detected only")
            lines.append(f"  {_safe(column.name)} · {_safe(kind.name)} · {', '.join(details)}")
        if table.primary_key:
            key = table.primary_key
            lines.append(f"  Primary key {_safe(key.name)} ({_sequence(key.columns)})")
        for foreign in table.foreign_keys:
            parent = f"{_safe(foreign.parent.schema_name)}.{_safe(foreign.parent.table)}"
            lines.append(
                f"  Foreign key {_safe(foreign.name)} ({_sequence(foreign.columns)}) "
                f"→ {parent} ({_sequence(foreign.parent_columns)})"
            )
        for unique in table.unique_keys:
            status = "MVP" if unique.supported else "Detected only"
            lines.append(f"  Unique {_safe(unique.name)} ({_sequence(unique.columns)}) · {status}")
        for check in table.checks:
            lines.append(f"  Check {_safe(check.name)} · {check.status}")
        for feature in table.features:
            if feature.reason:
                lines.append(f"  {_safe(feature.name)} · {feature.status} · {feature.reason}")
    return lines
