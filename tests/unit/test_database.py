"""Validation of explicit PostgreSQL endpoints."""

import pytest

from seed.config import ConfigError
from seed.database import parse_database_url


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
