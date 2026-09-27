"""Calendar boundary rules for T087 administrative-history retention."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.app.domain.audit.retention import administrative_retention_deadline


def test_t087_retention_uses_mexico_local_calendar_anniversary_at_year_boundary() -> None:
    event_time = datetime(2024, 1, 1, 5, 59, 59, 999999, tzinfo=timezone.utc)

    deadline = administrative_retention_deadline(event_time)

    local_event = event_time.astimezone(ZoneInfo("America/Mexico_City"))
    local_deadline = deadline.astimezone(ZoneInfo("America/Mexico_City"))
    assert local_event.strftime("%Y-%m-%d %H:%M:%S.%f") == (
        "2023-12-31 23:59:59.999999"
    )
    assert local_deadline.strftime("%Y-%m-%d %H:%M:%S.%f") == (
        "2024-12-31 23:59:59.999999"
    )
    assert deadline == datetime(2025, 1, 1, 5, 59, 59, 999999, tzinfo=timezone.utc)


def test_t087_retention_rejects_naive_event_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        administrative_retention_deadline(datetime(2024, 1, 1, 12, 0))
