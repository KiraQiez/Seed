"""Exercise SQL literal boundaries with the actual PostgreSQL parser."""

from io import StringIO

from conftest import PostgresFixture

from seed.exporting.sql import write_sql
from seed.generation.streaming import GeneratedRecord
from seed.metadata import ColumnSchema, ColumnType, TableId, TableSchema


def test_sql_preserves_quoted_names_typed_identity_and_hostile_text(
    postgres: PostgresFixture,
) -> None:
    postgres.sql("""
        CREATE SCHEMA "export SQL";
        CREATE TYPE "export SQL"."St""ate" AS ENUM ('new', 'done');
        CREATE TABLE "export SQL"."Par.ent" (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            state "export SQL"."St""ate",
            "No""te" text,
            computed bigint GENERATED ALWAYS AS (id + 1) STORED
        );
        CREATE TABLE "export SQL".child (
            parent_id bigint REFERENCES "export SQL"."Par.ent"
        );
    """)
    parent = TableId(schema="export SQL", table="Par.ent")
    child = TableId(schema="export SQL", table="child")
    bigint = ColumnType(name="bigint", supported=True)
    label = ColumnType(name="enum", supported=True, type_schema="export SQL", type_name='St"ate')
    note = ColumnType(name="text", supported=True)
    parent_schema = TableSchema(
        id=parent,
        kind="table",
        columns=(
            ColumnSchema(
                name="id",
                ordinal=0,
                type=bigint,
                nullable=False,
                default_kind="identity",
                identity="always",
            ),
            ColumnSchema(name="state", ordinal=1, type=label, nullable=True, default_kind="none"),
            ColumnSchema(name='No"te', ordinal=2, type=note, nullable=True, default_kind="none"),
            ColumnSchema(
                name="computed",
                ordinal=3,
                type=bigint,
                nullable=True,
                default_kind="none",
                generated="stored",
            ),
        ),
    )
    child_schema = TableSchema(
        id=child,
        kind="table",
        columns=(
            ColumnSchema(
                name="parent_id", ordinal=0, type=bigint, nullable=True, default_kind="none"
            ),
        ),
    )
    text = "é'\\\n\\q\r\t"
    output = StringIO()
    write_sql(
        output,
        [
            (
                parent_schema,
                [GeneratedRecord(parent, 0, {"id": 42, "state": "new", 'No"te': text})],
            ),
            (child_schema, [GeneratedRecord(child, 0, {"parent_id": 42})]),
        ],
    )
    script = output.getvalue()
    assert "OVERRIDING SYSTEM VALUE" in script
    assert "computed" not in script and "\n\\q" not in script
    assert all(
        line.startswith(("BEGIN;", "SET LOCAL ", "INSERT INTO ", "COMMIT;"))
        for line in script.splitlines()
    )
    postgres.sql(script)
    encoded = text.encode().hex()
    assert (
        postgres.sql("""
        SELECT p.id, p.computed, p.state, encode(convert_to(p."No""te", 'UTF8'), 'hex')
        FROM "export SQL"."Par.ent" p JOIN "export SQL".child c ON c.parent_id = p.id
    """)
        == f"42|43|new|{encoded}"
    )
