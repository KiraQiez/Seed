"""Typed schema metadata and deterministic serialization."""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type Capability = Literal["MVP", "Partial", "Detected only", "Future"]


class Metadata(BaseModel):
    model_config = ConfigDict(frozen=True)


class TableId(Metadata):
    schema_name: str = Field(alias="schema")
    table: str


class Target(Metadata):
    host: str
    port: int
    database: str
    schema_name: str = Field(alias="schema")


class Feature(Metadata):
    name: str
    status: Capability
    reason: str | None = None


class ColumnType(Metadata):
    name: str
    supported: bool
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    timezone: bool | None = None
    enum_labels: tuple[str, ...] = ()
    type_schema: str | None = None
    type_name: str | None = None
    collation: str | None = None


class ColumnSchema(Metadata):
    name: str
    ordinal: int
    type: ColumnType
    nullable: bool
    default_kind: str
    identity: str | None = None
    sequence_max: int | None = None
    generated: str | None = None


class Key(Metadata):
    name: str
    columns: tuple[str, ...]


class ForeignKey(Key):
    parent: TableId
    parent_columns: tuple[str, ...]
    match: str = "SIMPLE"
    validated: bool | None = None
    deferrable: bool = False
    enforced: bool | None = None
    on_update: str = "NO ACTION"
    on_delete: str = "NO ACTION"


class UniqueKey(Key):
    nulls_distinct: bool | None = None
    source: str = "constraint"
    supported: bool | None = None


class NumericBound(Metadata):
    column: str
    operator: str
    value: str


class Check(Key):
    status: Capability = "Detected only"
    validated: bool | None = None
    bounds: tuple[NumericBound, ...] = ()


class TableSchema(Metadata):
    id: TableId
    kind: str
    columns: tuple[ColumnSchema, ...]
    primary_key: Key | None = None
    foreign_keys: tuple[ForeignKey, ...] = ()
    unique_keys: tuple[UniqueKey, ...] = ()
    checks: tuple[Check, ...] = ()
    features: tuple[Feature, ...] = ()
    issues: tuple[str, ...] = ()


class DatabaseSchema(Metadata):
    target: Target
    server_major: int
    schemas: tuple[str, ...]
    tables: tuple[TableSchema, ...]
    fingerprint: str


@dataclass(frozen=True)
class Inspection:
    """Public metadata and private evidence for a later live comparison."""

    schema: DatabaseSchema
    catalog_identities: tuple[tuple[str, int], ...]
    definition_digest: str


def digest(value: object) -> str:
    """Fingerprint ordered, JSON-compatible structural data."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
