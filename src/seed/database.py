"""Open validated, read-only PostgreSQL sessions."""

import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from ipaddress import ip_address
from urllib.parse import parse_qsl, unquote, urlsplit

from psycopg import pq
from sqlalchemy import URL, Connection, create_engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from seed.config import ConfigError, DatabaseConfig


class DatabaseError(Exception):
    """A database failure with a safe diagnostic and CLI status."""

    def __init__(self, code: str, message: str, status: int = 3) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def parse_database_url(
    value: str,
    environ: Mapping[str, str] | None = None,
) -> URL:
    """Validate one explicit PostgreSQL TCP endpoint and its TLS settings."""
    environment = os.environ if environ is None else environ
    libpq_keys = {
        option.envvar.decode("ascii") for option in pq.Conninfo.get_defaults() if option.envvar
    }
    if libpq_keys.union({"PGREQUIRESSL", "PGSERVICEFILE", "PGSYSCONFDIR"}).intersection(
        environment
    ):
        raise ConfigError("Remove connection-affecting libpq environment overrides.")

    try:
        return _parse(value)
    except (ValueError, UnicodeError):
        raise ConfigError("The configured PostgreSQL URL is invalid or unsupported.") from None


def _parse(value: str) -> URL:
    if re.search(r"[\x00-\x20\x7f]|%(?![0-9a-fA-F]{2})|#", value) or not value.startswith(
        ("postgresql://", "postgresql+psycopg://")
    ):
        raise ValueError
    parts = urlsplit(value)
    authority = parts.netloc.rsplit("@", 1)[-1]
    if (
        parts.netloc.count("@") != 1
        or not parts.username
        or not parts.password
        or not parts.hostname
        or not parts.path.startswith("/")
        or "/" in parts.path[1:]
        or not re.fullmatch(r"(?:\[[0-9a-fA-F:.]+\]|[a-zA-Z0-9.-]+)(?::[0-9]+)?", authority)
    ):
        raise ValueError

    host = parts.hostname
    try:
        address = ip_address(host)
    except ValueError:
        label = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
        host = host.removesuffix(".")
        if len(host) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", host):
            raise ValueError from None
        loopback = False
    else:
        host = str(address)
        loopback = address.is_loopback
    port = parts.port if parts.port is not None else 5432
    if not 1 <= port <= 65_535:
        raise ValueError

    username = unquote(parts.username, errors="strict")
    password = unquote(parts.password, errors="strict")
    database = unquote(parts.path[1:], errors="strict")
    if not all((username, password, database)) or any(
        "\x00" in item for item in (username, password, database)
    ):
        raise ValueError
    options = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, errors="strict")
    query = dict(options)
    if len(query) != len(options) or any(
        key not in {"sslmode", "sslrootcert"} or not option or "\x00" in option
        for key, option in options
    ):
        raise ValueError
    query.setdefault("sslmode", "disable" if loopback else "verify-full")
    if query["sslmode"] != "verify-full" and not (loopback and query["sslmode"] == "disable"):
        raise ValueError
    return URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
        query=query,
    )


@contextmanager
def open_session(url: URL, config: DatabaseConfig) -> Iterator[Connection]:
    """Open a single physical PostgreSQL connection without pooling."""
    engine = create_engine(
        url,
        connect_args={"connect_timeout": config.connect_timeout},
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        try:
            connection = engine.connect()
        except SQLAlchemyError as error:
            if isinstance(error, DBAPIError) and (
                type(error.orig).__name__ == "ConnectionTimeout"
                or "timeout expired" in str(error.orig).lower()
            ):
                raise DatabaseError(
                    "CONNECTION_TIMEOUT", "The PostgreSQL connection timed out."
                ) from None
            raise DatabaseError("CONNECTION_FAILED", "Could not connect to PostgreSQL.") from None
        with connection:
            yield connection
    finally:
        engine.dispose()


@contextmanager
def read_snapshot(connection: Connection) -> Iterator[None]:
    """Start and finish a read-only snapshot on an open connection."""
    connection.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
    with connection.begin():
        connection.execute(text("SET LOCAL search_path TO pg_catalog"))
        yield


@contextmanager
def read_session(url: URL, config: DatabaseConfig) -> Iterator[Connection]:
    """Yield a transaction pinned to a read-only PostgreSQL snapshot."""
    with open_session(url, config) as connection:
        try:
            with read_snapshot(connection):
                yield connection
        except SQLAlchemyError:
            raise DatabaseError(
                "SCHEMA_INSPECTION_FAILED", "Could not inspect the PostgreSQL schema.", 4
            ) from None
