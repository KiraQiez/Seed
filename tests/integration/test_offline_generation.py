"""Integrate generation with a real schema snapshot on supported PostgreSQL releases."""

from decimal import Decimal

from conftest import PostgresFixture
from test_schema import snapshot

from seed.config import parse_config
from seed.generation.engine import generate_batches
from seed.planning.plan import build_plan


def test_offline_rows_follow_reflected_constraints_and_leave_database_unchanged(
    postgres: PostgresFixture,
) -> None:
    postgres.sql("""
        CREATE SCHEMA offline_sample;
        CREATE TABLE offline_sample.parent (id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
        CREATE TABLE offline_sample.child (
            parent_id integer REFERENCES offline_sample.parent (id) NOT NULL UNIQUE,
            amount numeric(6, 2) NOT NULL CHECK (amount > 3.00 AND amount < 3.02),
            short_name varchar(3) NOT NULL,
            computed numeric GENERATED ALWAYS AS (amount * 2) STORED
        );
    """)
    state_query = """
        SELECT (SELECT count(*) FROM offline_sample.parent),
               (SELECT count(*) FROM offline_sample.child),
               last_value, is_called
        FROM offline_sample.parent_id_seq
    """
    before = postgres.sql(state_query)
    schema = snapshot(postgres, "offline_sample").schema
    config = parse_config(
        'version=1\n[database]\nurl_env="SEED_TEST_URL"\nschema="offline_sample"\n'
        "[generation]\nnull_rate=0\n[tables.child]\nrows=3\n[tables.parent]\nrows=3\n"
    )
    plan = build_plan(config, schema, [])
    assert plan.compatibility["offline"].executable
    rows = [row for batch in generate_batches(plan, schema, config, batch_size=2) for row in batch]
    assert [row.values["id"] for row in rows[:3]] == [1, 2, 3]
    assert {row.values["parent_id"] for row in rows[3:]} == {1, 2, 3}
    assert all(row.values["amount"] == Decimal("3.01") for row in rows[3:])
    assert all("computed" not in row.values for row in rows[3:])
    assert postgres.sql(state_query) == before
