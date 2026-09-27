"""Calendar retention rules for administrative-history associations."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


_BUSINESS_TIMEZONE = ZoneInfo("America/Mexico_City")


def administrative_retention_deadline(occurred_at: datetime) -> datetime:
    """Return the same local wall time one calendar year after an event.

    A date such as February 29 is clamped to the final day of February in the
    following year, matching the approved administrative-history policy.
    """

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("Administrative event time must be timezone-aware.")

    local_time = occurred_at.astimezone(_BUSINESS_TIMEZONE)
    next_year = local_time.year + 1
    if local_time.month == 2 and local_time.day == 29:
        local_time = local_time.replace(year=next_year, day=28)
    else:
        local_time = local_time.replace(year=next_year)
    return local_time.astimezone(timezone.utc)
