"""Own a disposable, local PostgreSQL project for integration tests."""

import json
import os
import re
import secrets
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

COMPOSE_FILE = Path(__file__).with_name("compose.yaml")


def _docker(args: list[str], env: dict[str, str], timeout: int = 30) -> str:
    try:
        process = subprocess.run(
            ["docker", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(f"Docker fixture unavailable or timed out ({args[0]}).") from None
    if process.returncode:
        raise RuntimeError(f"Docker fixture command failed ({args[0]}).")
    return process.stdout.strip()


@dataclass(frozen=True)
class PostgresFixture:
    """A database created and owned by the current test session."""

    compose: list[str]
    env: dict[str, str] = field(repr=False)
    database: str
    port: int
    major: str

    @property
    def url(self) -> str:
        return (
            f"postgresql://seed_fixture:{self.env['SEED_FIXTURE_PASSWORD']}"
            f"@127.0.0.1:{self.port}/{self.database}"
        )

    def sql(self, statement: str) -> str:
        """Execute a fixture-owned setup or observation statement."""
        return _docker(
            [
                *self.compose,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-X",
                "-U",
                "seed_fixture",
                "-d",
                self.database,
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                statement,
            ],
            self.env,
        )


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresFixture]:
    major = os.environ.get("SEED_TEST_POSTGRES_MAJOR", "17")
    if major not in {"15", "16", "17", "18", "19"}:
        pytest.fail("Integration fixture requires PostgreSQL major 15–19.")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("COMPOSE_", "PG")) and key not in {"DOCKER_HOST", "DATABASE_URL"}
    }
    raw_context = _docker(["context", "inspect", "--format", "{{json .}}"], env)
    context = json.loads(raw_context)
    if not context["Endpoints"]["docker"]["Host"].startswith(("unix://", "npipe://")):
        pytest.fail("Integration fixture requires a local Docker context.")
    token = secrets.token_hex(10)
    project = f"seed-fixture-{token}"
    database = f"seed_fixture_{token}"
    env.update(
        SEED_TEST_POSTGRES_MAJOR=major,
        SEED_FIXTURE_DATABASE=database,
        SEED_FIXTURE_PASSWORD=secrets.token_hex(24),
    )
    docker = ["--context", context["Name"]]
    compose = [
        *docker,
        "compose",
        "--env-file",
        os.devnull,
        "-f",
        str(COMPOSE_FILE),
        "-p",
        project,
    ]
    if _docker(
        [*docker, "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"], env
    ):
        pytest.fail("Integration fixture project already exists.")
    try:
        _docker([*compose, "up", "-d", "--wait", "--wait-timeout", "90"], env, timeout=160)
        container = _docker([*compose, "ps", "-q", "postgres"], env)
        owner = _docker(
            [
                *docker,
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}',
                container,
            ],
            env,
        )
        port = _docker([*compose, "port", "postgres", "5432"], env)
        match = re.fullmatch(r"127\.0\.0\.1:([0-9]+)", port)
        if owner != project or not match:
            pytest.fail("Could not verify ownership and loopback port of integration fixture.")
        fixture = PostgresFixture(compose, env, database, int(match[1]), major)
        identity = fixture.sql(
            "SELECT current_database() || ':' || current_setting('server_version_num')"
        )
        actual_database, _, server_version = identity.partition(":")
        if actual_database != database or int(server_version) // 10000 != int(major):
            pytest.fail("Integration database identity or version differed from fixture.")
        yield fixture
    finally:
        _docker([*compose, "down", "--volumes"], env, timeout=90)
        if _docker(
            [*docker, "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"], env
        ):
            pytest.fail("An integration fixture container remained after teardown.")
