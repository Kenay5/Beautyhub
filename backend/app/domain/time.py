"""Time-zone-safe temporal rules for BeautyHub."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


BUSINESS_TIME_ZONE = ZoneInfo("America/Mexico_City")


class InstantValidationError(ValueError):
    """Raised when a temporal value is not an unambiguous absolute instant."""


def normalize_instant(instant: datetime) -> datetime:
    """Validate an aware instant and normalize it to UTC for comparisons."""

    if not isinstance(instant, datetime):
        raise InstantValidationError("instant must be a datetime.")
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise InstantValidationError("instant must include a time zone.")
    return instant.astimezone(timezone.utc)


def to_business_time(instant: datetime) -> datetime:
    """Convert an absolute instant to BeautyHub's official business zone."""

    return normalize_instant(instant).astimezone(BUSINESS_TIME_ZONE)


def business_datetime(local_date: date, local_time: time) -> datetime:
    """Create an explicit BeautyHub business-time instant from date and time."""

    if not isinstance(local_date, date) or isinstance(local_date, datetime):
        raise InstantValidationError("local date must be a date.")
    if not isinstance(local_time, time):
        raise InstantValidationError("local time must be a time.")
    if local_time.tzinfo is not None:
        raise InstantValidationError("local time must not include a time zone.")
    return datetime.combine(local_date, local_time, BUSINESS_TIME_ZONE)
