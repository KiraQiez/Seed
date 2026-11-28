"""Render schema inspection metadata without executing terminal control sequences."""

from seed.metadata import DatabaseSchema


def safe_text(text: str) -> str:
    """Escape control characters before rendering terminal text."""
    return "".join(char if char.isprintable() else f"\\u{ord(char):04x}" for char in text)


def _sequence(names: tuple[str, ...]) -> str:
    return ", ".join(map(safe_text, names))


def inspection_lines(report: DatabaseSchema) -> list[str]:
    """Build readable lines for the terminal schema report."""
    lines = [
        f"PostgreSQL {report.server_major} · {safe_text(report.target.database)} "
        f"· schema {safe_text(report.target.schema_name)}",
        f"{len(report.tables)} relations · fingerprint {report.fingerprint}",
    ]
    for table in report.tables:
        lines.append(
            f"{safe_text(table.id.schema_name)}.{safe_text(table.id.table)} ({table.kind})"
        )
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
            lines.append(
                f"  {safe_text(column.name)} · {safe_text(kind.name)} · {', '.join(details)}"
            )
        if table.primary_key:
            key = table.primary_key
            lines.append(f"  Primary key {safe_text(key.name)} ({_sequence(key.columns)})")
        for foreign in table.foreign_keys:
            parent = f"{safe_text(foreign.parent.schema_name)}.{safe_text(foreign.parent.table)}"
            lines.append(
                f"  Foreign key {safe_text(foreign.name)} ({_sequence(foreign.columns)}) "
                f"→ {parent} ({_sequence(foreign.parent_columns)})"
            )
        for unique in table.unique_keys:
            status = "MVP" if unique.supported else "Detected only"
            lines.append(
                f"  Unique {safe_text(unique.name)} ({_sequence(unique.columns)}) · {status}"
            )
        for check in table.checks:
            lines.append(f"  Check {safe_text(check.name)} · {check.status}")
        for feature in table.features:
            if feature.reason:
                lines.append(f"  {safe_text(feature.name)} · {feature.status} · {feature.reason}")
    return lines
