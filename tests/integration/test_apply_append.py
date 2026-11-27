"""Guarded append and existing-parent key pools."""

from pathlib import Path

import pytest
from conftest import PostgresFixture
from test_apply_safety import config_for

from seed.apply import apply_preflight
from seed.database import open_session, parse_database_url
from seed.insertion import PostgreSQLWriter, execute_apply
from seed.metadata import TableSchema
from seed.planning import PlanRequest
from seed.streaming import RecordBatch


def test_append_checks_indexed_existing_keys_and_null_semantics(postgres: PostgresFixture) -> None:
    postgres.sql("""
        CREATE SCHEMA append_fixture;
        CREATE TABLE append_fixture.items (code integer NOT NULL UNIQUE);
        CREATE TABLE append_fixture.strict_null (code integer UNIQUE NULLS NOT DISTINCT);
        CREATE TABLE append_fixture.distinct_null (code integer UNIQUE);
        INSERT INTO append_fixture.items VALUES (1);
        INSERT INTO append_fixture.strict_null VALUES (NULL);
        INSERT INTO append_fixture.distinct_null VALUES (NULL);
    """)
    url = parse_database_url(postgres.url, {})
    config = config_for(
        postgres,
        "append_fixture",
        append=True,
        tables="""
[rules.items.code]
generator = "integer"
min = 1
max = 2
[rules.strict_null.code]
null_rate = 1
[rules.distinct_null.code]
null_rate = 1
""",
    )
    with open_session(url, config.database) as connection:
        for name in ("items", "distinct_null", "strict_null"):
            request = PlanRequest(Path("unused"), None, [name], 1, None, None)
            approved = apply_preflight(connection, url, config, request)
            applied = execute_apply(connection, url, config, request, approved)
            if name == "strict_null":
                assert applied.status == 4 and applied.insertion.outcome == "rolled_back"
                assert applied.issue is not None and applied.issue.code == "RETRY_EXHAUSTED"
                assert applied.insertion.counts is None
            else:
                assert applied.status == 0 and applied.insertion.outcome == "committed"
    assert postgres.sql("SELECT code FROM append_fixture.items ORDER BY code") == "1\n2"
    assert postgres.sql("SELECT count(*) FROM append_fixture.distinct_null") == "2"
    assert postgres.sql("SELECT count(*) FROM append_fixture.strict_null") == "1"


def test_existing_parent_pool_is_bounded_ordered_and_independent_of_append(
    postgres: PostgresFixture,
) -> None:
    postgres.sql("""
        CREATE SCHEMA reuse_fixture;
        CREATE TABLE reuse_fixture.parent (id integer PRIMARY KEY);
        CREATE TABLE reuse_fixture.child (
            parent_id integer NOT NULL REFERENCES reuse_fixture.parent(id)
        );
        INSERT INTO reuse_fixture.parent SELECT generate_series(100, 10104) ORDER BY 1 DESC;
    """)
    url = parse_database_url(postgres.url, {})
    config = config_for(
        postgres,
        "reuse_fixture",
        tables="[tables.parent]\nrows=0\nreuse_existing=true",
    )
    request = PlanRequest(Path("unused"), None, ["child"], 3, None, None)
    with open_session(url, config.database) as connection:
        approved = apply_preflight(connection, url, config, request)
        with connection.begin():
            writer = PostgreSQLWriter(connection)
            keys = list(writer.load_existing(approved.plan.tables[-1].dependencies[0]))
            assert len(keys) == 10_000 and keys[0] == (100,) and keys[-1] == (10099,)
        result = execute_apply(connection, url, config, request, approved)
        assert result.status == 0 and result.insertion.counts is not None
        assert [item.table.table for item in result.insertion.counts] == ["child"]
    assert postgres.sql("SELECT count(*) FROM reuse_fixture.child WHERE parent_id <= 10099") == "3"


def test_disappearing_reused_parent_rolls_back_prior_inserts(
    postgres: PostgresFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    postgres.sql("""
        CREATE SCHEMA reuse_stale_fixture;
        CREATE TABLE reuse_stale_fixture.parent (id integer PRIMARY KEY);
        CREATE TABLE reuse_stale_fixture.a_first (id integer);
        CREATE TABLE reuse_stale_fixture.child (
            parent_id integer NOT NULL REFERENCES reuse_stale_fixture.parent (id)
        );
        INSERT INTO reuse_stale_fixture.parent VALUES (7);
    """)
    url = parse_database_url(postgres.url, {})
    config = config_for(
        postgres,
        "reuse_stale_fixture",
        tables="""
[tables.parent]
rows=0
reuse_existing=true
[tables.a_first]
rows=2
[tables.child]
rows=1
""",
    )
    request = PlanRequest(Path("unused"), None, [], None, None, None)
    original = PostgreSQLWriter.write

    def remove_parent(
        writer: PostgreSQLWriter,
        model: TableSchema,
        batch: RecordBatch,
        identities: tuple[str, ...],
    ) -> RecordBatch:
        if model.id.table == "child":
            postgres.sql("DELETE FROM reuse_stale_fixture.parent WHERE id = 7")
        return original(writer, model, batch, identities)

    monkeypatch.setattr(PostgreSQLWriter, "write", remove_parent)
    with open_session(url, config.database) as connection:
        approved = apply_preflight(connection, url, config, request)
        result = execute_apply(connection, url, config, request, approved)
    assert result.status == 6 and result.insertion.outcome == "rolled_back"
    assert result.insertion.counts is None
    assert postgres.sql("SELECT count(*) FROM reuse_stale_fixture.a_first") == "0"
    assert postgres.sql("SELECT count(*) FROM reuse_stale_fixture.child") == "0"
