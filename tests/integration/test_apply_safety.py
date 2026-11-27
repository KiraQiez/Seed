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


def test_guard_refuses_changes_after_preflight(postgres: PostgresFixture) -> None:
    from seed.apply import begin_guarded_write

    postgres.sql("""
        CREATE SCHEMA apply_changed_fixture;
        CREATE TABLE apply_changed_fixture.items (id integer);
    """)
    url = parse_database_url(postgres.url, {})
    config = config_for(postgres, "apply_changed_fixture")
    request = PlanRequest(Path("unused"), None, [], None, None, None)
    with open_session(url, config.database) as connection:
        approved = apply_preflight(connection, url, config, request)
        postgres.sql("ALTER TABLE apply_changed_fixture.items ADD COLUMN label text")
        with pytest.raises(ApplyError) as refused:
            begin_guarded_write(connection, url, config, request, approved)
        assert refused.value.code == "TARGET_CHANGED"
        assert not connection.in_transaction()

        approved = apply_preflight(connection, url, config, request)
        postgres.sql("INSERT INTO apply_changed_fixture.items (id) VALUES (1)")
        with pytest.raises(ApplyError) as occupied:
            begin_guarded_write(connection, url, config, request, approved)
        assert occupied.value.code == "TARGET_NOT_EMPTY"


def test_guard_checks_lock_permissions_and_times_out_behind_other_writer(
    postgres: PostgresFixture,
) -> None:
    from sqlalchemy import text

    from seed.apply import begin_guarded_write

    postgres.sql("""
        CREATE SCHEMA apply_lock_fixture;
        CREATE TABLE apply_lock_fixture.items (id integer);
        CREATE ROLE seed_limited LOGIN PASSWORD 'throwaway-fixture';
        GRANT USAGE ON SCHEMA apply_lock_fixture TO seed_limited;
        GRANT SELECT, INSERT ON apply_lock_fixture.items TO seed_limited;
    """)
    url = parse_database_url(postgres.url, {})
    config = config_for(postgres, "apply_lock_fixture")
    request = PlanRequest(Path("unused"), None, [], None, None, None)
    limited = url.set(username="seed_limited", password="throwaway-fixture")
    with open_session(limited, config.database) as connection:
        approved = apply_preflight(connection, limited, config, request)
        with pytest.raises(ApplyError) as refused:
            begin_guarded_write(connection, limited, config, request, approved)
        assert refused.value.code == "LOCK_UNAVAILABLE"
        assert not connection.in_transaction()

    with open_session(url, config.database) as app, open_session(url, config.database) as writer:
        approved = apply_preflight(app, url, config, request)
        transaction = writer.begin()
        try:
            writer.execute(text("INSERT INTO apply_lock_fixture.items VALUES (1)"))
            with pytest.raises(ApplyError) as refused:
                begin_guarded_write(app, url, config, request, approved)
            assert refused.value.code == "LOCK_UNAVAILABLE"
        finally:
            transaction.rollback()
        guarded = begin_guarded_write(app, url, config, request, approved)
        try:
            assert app.scalar(text("SHOW lock_timeout")) == "5s"
            assert app.scalar(text("SHOW transaction_isolation")) == "read committed"
            assert app.scalar(text("SHOW statement_timeout")) == "1min"
        finally:
            guarded.rollback()
