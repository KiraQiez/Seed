"""Validation of explicit PostgreSQL endpoints."""

import pytest

from seed.config import ConfigError
from seed.postgres.connection import parse_database_url


def test_connection_options_and_decoding() -> None:
    url = parse_database_url("postgresql://user:p%40ss@[::1]/Dev%20Database", {})
    assert (url.host, url.port, url.database) == ("::1", 5432, "Dev Database")
    assert url.query["sslmode"] == "disable"
    assert url.password == "p@ss"
    assert (
        parse_database_url("postgresql://u:p@db.example/seed", {}).query["sslmode"] == "verify-full"
    )


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://u:private@host,host/db",
        "postgresql://u:private@/db?host=/tmp",
        "postgresql://u:private@host/db?sslmode=disable",
        "postgresql://u:private@host/db?service=other",
        "postgresql://u:private@host/db?sslmode=verify-full&sslmode=verify-full",
        "postgresql://u:private@host:0/db",
        "postgresql://u:private@[::1]invalid/db",
        "postgresql://u:private@host/",
    ],
)
def test_invalid_urls_are_redacted(value: str) -> None:
    with pytest.raises(ConfigError) as caught:
        parse_database_url(value, {})
    assert "private" not in str(caught.value)


def test_rejects_libpq_override() -> None:
    with pytest.raises(ConfigError, match="libpq"):
        parse_database_url("postgresql://u:p@127.0.0.1/db", {"PGHOSTADDR": "private"})


def test_connection_timeout_is_structured() -> None:
    import socket

    from seed.config import DatabaseConfig
    from seed.postgres.connection import DatabaseError, read_session

    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        port = endpoint.getsockname()[1]
        url = parse_database_url(f"postgresql://user:secret@127.0.0.1:{port}/test", {})
        config = DatabaseConfig(url_env="SEED_TEST_URL", connect_timeout=2)
        with pytest.raises(DatabaseError) as caught, read_session(url, config):
            pytest.fail("a TCP listener cannot respond to the PostgreSQL handshake")
        assert caught.value.code == "CONNECTION_TIMEOUT"
        assert "secret" not in str(caught.value)
