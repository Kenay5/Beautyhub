"""Calendar rules for T081 deactivated-staff identity retention."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.app.domain.audit.retention import administrative_retention_deadline


def test_t081_deadline_uses_local_calendar_anniversary_and_clamps_leap_day() -> None:
    occurred_at = datetime(2024, 2, 29, 18, 15, tzinfo=timezone.utc)

    assert administrative_retention_deadline(occurred_at) == datetime(
        2025, 2, 28, 18, 15, tzinfo=timezone.utc
    )


def test_t081_deadline_preserves_local_wall_time_across_timezone_offset() -> None:
    occurred_at = datetime(2024, 7, 1, 14, 30, tzinfo=timezone.utc)

    deadline = administrative_retention_deadline(occurred_at)

    assert deadline.astimezone(ZoneInfo("America/Mexico_City")).strftime(
        "%Y-%m-%d %H:%M"
    ) == "2025-07-01 08:30"
    assert deadline == datetime(2025, 7, 1, 14, 30, tzinfo=timezone.utc)


def test_t081_rejects_naive_event_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        administrative_retention_deadline(datetime(2024, 1, 1, 12, 0))
