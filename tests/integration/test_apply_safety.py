"""Apply preflight against the owned disposable fixture."""

from pathlib import Path

import pytest
from conftest import PostgresFixture

from seed.apply import ApplyError, apply_preflight
from seed.config import SeedConfig, parse_config
from seed.database import open_session, parse_database_url
from seed.planning import PlanRequest


def config_for(
    postgres: PostgresFixture,
    schema: str,
    *,
    append: bool = False,
    tables: str = "",
) -> SeedConfig:
    return parse_config(f"""
version = 1
[database]
url_env = "SEED_TEST_URL"
schema = "{schema}"
[generation]
null_rate = 0
batch_size = 2
[safety]
environment = "test"
allow_existing_data = {str(append).lower()}
[safety.target]
host = "127.0.0.1"
port = {postgres.port}
database = "{postgres.database}"
schema = "{schema}"
{tables}
""")


def test_preflight_closes_read_snapshot_and_refuses_existing_rows(
    postgres: PostgresFixture,
) -> None:
    postgres.sql("""
        CREATE SCHEMA apply_preflight_fixture;
        CREATE TABLE apply_preflight_fixture.items (id bigint GENERATED ALWAYS AS IDENTITY);
    """)
    state = "SELECT last_value, is_called FROM apply_preflight_fixture.items_id_seq"
    before = postgres.sql(state)
    url = parse_database_url(postgres.url, {})
    config = config_for(postgres, "apply_preflight_fixture")
    request = PlanRequest(Path("unused"), None, ["items"], 2, None, None)
    with open_session(url, config.database) as connection:
        approved = apply_preflight(connection, url, config, request)
        assert approved.plan.total_rows == 2
        assert not connection.in_transaction()
    assert postgres.sql(state) == before
    assert postgres.sql("SELECT count(*) FROM apply_preflight_fixture.items") == "0"

    postgres.sql("INSERT INTO apply_preflight_fixture.items DEFAULT VALUES")
    with open_session(url, config.database) as connection, pytest.raises(ApplyError) as caught:
        apply_preflight(connection, url, config, request)
    assert caught.value.code == "TARGET_NOT_EMPTY"
