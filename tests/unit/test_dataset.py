"""Lossless preview and export scalar projections."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from seed.dataset import json_value


def test_dataset_scalar_serialization() -> None:
    assert json_value(2**63 - 1, "bigint") == "9223372036854775807"
    assert json_value(Decimal("123.040"), "numeric") == "123.040"
    assert json_value(140, "integer") == 140
    assert json_value(None, "boolean") is None
    assert json_value(False, "boolean") is False
    assert json_value(date(2025, 1, 1), "date") == "2025-01-01"
    assert json_value(datetime(2025, 1, 1), "timestamp") == "2025-01-01T00:00:00"
    aware = datetime(2025, 1, 1, 4, tzinfo=timezone(timedelta(hours=4)))
    assert json_value(aware, "timestamptz") == "2025-01-01T00:00:00+00:00"
    assert json_value(UUID(int=1), "uuid") == "00000000-0000-0000-0000-000000000001"
