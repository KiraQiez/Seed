"""Integration coverage for the read-only snapshot and sanitized connection failures."""

import pytest
from conftest import PostgresFixture
from sqlalchemy import text

from seed.config import DatabaseConfig
from seed.postgres.connection import DatabaseError, parse_database_url, read_session


def test_read_only_connection(postgres: PostgresFixture) -> None:
    config = DatabaseConfig(url_env="SEED_TEST_URL")
    with read_session(parse_database_url(postgres.url, {}), config) as connection:
        assert connection.scalar(text("SELECT current_database()")) == postgres.database
        assert connection.scalar(text("SHOW transaction_read_only")) == "on"
        assert connection.scalar(text("SHOW transaction_isolation")) == "repeatable read"


def test_invalid_password_is_redacted(postgres: PostgresFixture) -> None:
    url = parse_database_url(postgres.url, {}).set(password="private-invalid-password")
    config = DatabaseConfig(url_env="SEED_TEST_URL")
    with pytest.raises(DatabaseError) as caught, read_session(url, config):
        pytest.fail("unexpected connection")
    assert caught.value.code == "CONNECTION_FAILED"
    assert "private-invalid-password" not in str(caught.value)
