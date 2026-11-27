"""Schema reflection with ordered identifiers, types, and keys."""

from conftest import PostgresFixture

from seed.config import DatabaseConfig
from seed.database import parse_database_url, read_session
from seed.schema import Inspection, reflect_schema


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
