"""Smoke-check the disposable PostgreSQL owner and server version."""

from conftest import PostgresFixture


def test_fixture_identity(postgres: PostgresFixture) -> None:
    assert postgres.sql("SELECT current_database()") == postgres.database
    assert postgres.sql("SHOW server_version_num").startswith(postgres.major)
