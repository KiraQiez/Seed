"""Apply gating and confirmation behavior."""

import pytest

from seed.apply import ApplyError, check_target, confirm_apply, validate_apply_options
from seed.config import ConfigError, parse_config
from seed.database import parse_database_url

_BASE = 'version=1\n[database]\nurl_env="SEED_TEST_URL"\nschema="My.Schema"\n'
_TARGET = """
[safety]
environment = "test"
[safety.target]
host = "LOCALHOST."
port = 5544
database = "my_database"
schema = "My.Schema"
"""


def test_apply_requires_an_independent_normalized_exact_target() -> None:
    url = parse_database_url("postgresql://u:p@localhost:5544/my_database", {})
    check_target(parse_config(_BASE + _TARGET), url)
    with pytest.raises(ApplyError, match="independently|requires"):
        check_target(parse_config(_BASE), url)
    for modified in (
        url.set(port=1234),
        url.set(database="other"),
        url.set(host="example.com"),
    ):
        with pytest.raises(ApplyError) as caught:
            check_target(parse_config(_BASE + _TARGET), modified)
        assert caught.value.code == "TARGET_MISMATCH"
    with pytest.raises(ApplyError):
        check_target(parse_config(_BASE + _TARGET, schema="other"), url)


def test_confirmation_and_dry_run_options() -> None:
    with pytest.raises(ConfigError):
        validate_apply_options(yes=True, dry_run=True)
    confirm_apply(yes=True, interactive=False, prompt=lambda: pytest.fail("never prompt"))
    confirm_apply(yes=False, interactive=True, prompt=lambda: " YES ")
    with pytest.raises(ApplyError) as rejected:
        confirm_apply(yes=False, interactive=False, prompt=lambda: pytest.fail("never prompt"))
    assert rejected.value.code == "CONFIRMATION_REQUIRED"
    for reply in ("", "n", "certainly"):
        with pytest.raises(ApplyError) as rejected:
            confirm_apply(yes=False, interactive=True, prompt=lambda: reply)
        assert rejected.value.code == "CANCELLED"

    def eof() -> str:
        raise EOFError

    with pytest.raises(ApplyError, match="not confirmed"):
        confirm_apply(yes=False, interactive=True, prompt=eof)
