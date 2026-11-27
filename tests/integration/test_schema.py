"""Schema reflection with ordered identifiers, types, and keys."""

from conftest import PostgresFixture

from seed.config import DatabaseConfig
from seed.metadata import Inspection
from seed.postgres.connection import parse_database_url, read_session
from seed.postgres.schema import reflect_schema


def snapshot(postgres: PostgresFixture, schema: str) -> Inspection:
    url = parse_database_url(postgres.url, {})
    with read_session(url, DatabaseConfig(url_env="SEED_TEST_URL")) as connection:
        return reflect_schema(connection, url, schema)


def test_reflects_exact_identifiers_and_composite_order(postgres: PostgresFixture) -> None:
    postgres.sql("""
        CREATE SCHEMA "Seed.Tests";
        CREATE TYPE "Seed.Tests"."Order.State" AS ENUM ('new', 'done');
        CREATE TABLE "Seed.Tests"."Parent.Items" (
            second integer NOT NULL, first varchar(8) NOT NULL, PRIMARY KEY (first, second)
        );
        CREATE TABLE "Seed.Tests"."Child.Items" (
            left_key varchar(8), right_key integer,
            state "Seed.Tests"."Order.State" NOT NULL,
            amount numeric(8, 2) NOT NULL,
            CONSTRAINT "Reference.Key" FOREIGN KEY (left_key, right_key)
                REFERENCES "Seed.Tests"."Parent.Items" (first, second)
        )
    """)
    result = snapshot(postgres, "Seed.Tests")
    child, parent = result.schema.tables
    assert child.id.table == "Child.Items"
    assert parent.primary_key is not None
    assert parent.primary_key.columns == ("first", "second")
    assert child.foreign_keys[0].columns == ("left_key", "right_key")
    assert child.foreign_keys[0].parent == parent.id
    assert child.foreign_keys[0].parent_columns == ("first", "second")
    assert child.columns[0].nullable
    assert child.columns[2].type.enum_labels == ("new", "done")
    assert child.columns[3].type.scale == 2
    assert result == snapshot(postgres, "Seed.Tests")


def test_catalog_distinguishes_supported_and_detected_features(postgres: PostgresFixture) -> None:
    postgres.sql("""
        CREATE SCHEMA catalog_demo;
        CREATE TABLE catalog_demo.sample (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            serial_number serial,
            amount numeric(10, 2) CHECK (amount >= 1 AND amount <= 99),
            score integer CHECK (score > 1 OR score < 0),
            text_value text DEFAULT 'private-default',
            computed numeric GENERATED ALWAYS AS (amount * 2) STORED,
            CONSTRAINT unique_score UNIQUE NULLS NOT DISTINCT (score)
        );
        CREATE UNIQUE INDEX partial_amount ON catalog_demo.sample (amount) WHERE amount > 9;
        CREATE UNIQUE INDEX expression_text ON catalog_demo.sample (lower(text_value));
        ALTER TABLE catalog_demo.sample ENABLE ROW LEVEL SECURITY;
        CREATE FUNCTION catalog_demo.observe() RETURNS trigger LANGUAGE plpgsql AS
            'BEGIN RETURN NEW; END';
        CREATE TRIGGER sample_trigger BEFORE INSERT ON catalog_demo.sample
            FOR EACH ROW EXECUTE FUNCTION catalog_demo.observe();
    """)
    inspection = snapshot(postgres, "catalog_demo")
    (table,) = inspection.schema.tables
    columns = {column.name: column for column in table.columns}
    assert columns["id"].identity == "always"
    assert columns["id"].default_kind == "identity"
    assert columns["serial_number"].default_kind == "owned_serial"
    assert columns["computed"].generated == "stored"
    assert columns["text_value"].default_kind == "literal"
    checks = {check.name: check for check in table.checks}
    assert [bound.operator for bound in checks["sample_amount_check"].bounds] == [">=", "<="]
    assert checks["sample_score_check"].status == "Detected only"
    indexes = {key.name: key for key in table.unique_keys}
    assert indexes["unique_score"].nulls_distinct is False
    assert indexes["unique_score"].supported is True
    assert indexes["partial_amount"].supported is False
    assert indexes["expression_text"].supported is False
    assert {"ROW_LEVEL_SECURITY", "ENABLED_SERVER_LOGIC", "UNSUPPORTED_CHECK"} <= set(table.issues)
    serialized = inspection.schema.model_dump_json(by_alias=True)
    assert "private-default" not in serialized
    assert "RETURN NEW" not in serialized

    postgres.sql("ALTER TABLE catalog_demo.sample ALTER COLUMN text_value SET DEFAULT 'other'")
    changed = snapshot(postgres, "catalog_demo")
    assert changed.schema.fingerprint == inspection.schema.fingerprint
    assert changed.definition_digest != inspection.definition_digest
