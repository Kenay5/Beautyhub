"""Rules for the first durable appointment reminder."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.domain.time import normalize_instant


INITIAL_REMINDER_NOTICE = timedelta(hours=24)
REMINDER_PROCESSING_MINIMUM_NOTICE = timedelta(minutes=60)
SCHEDULED_REMINDER_STATUS = "scheduled"
CLAIMED_REMINDER_STATUS = "claimed"
COMPLETED_REMINDER_STATUS = "completed"
INVALIDATED_REMINDER_STATUS = "invalidated"
OMITTED_REMINDER_STATUS = "omitted"
PENDING_REMINDER_STATUSES = frozenset(
    {SCHEDULED_REMINDER_STATUS, CLAIMED_REMINDER_STATUS}
)


def is_initial_reminder_eligible(
    *,
    scheduled_start: datetime,
    current_time: datetime,
) -> bool:
    """Return whether confirmation occurs strictly more than 24 hours ahead."""

    return (
        normalize_instant(scheduled_start) - normalize_instant(current_time)
        > INITIAL_REMINDER_NOTICE
    )


def initial_reminder_send_at(scheduled_start: datetime) -> datetime:
    """Return the absolute instant exactly 24 hours before the appointment."""

    return normalize_instant(scheduled_start) - INITIAL_REMINDER_NOTICE


def is_due_reminder_timely(
    *,
    scheduled_start: datetime,
    current_time: datetime,
) -> bool:
    """Return whether a due reminder still has strictly more than 60 minutes."""

    return (
        normalize_instant(scheduled_start) - normalize_instant(current_time)
        > REMINDER_PROCESSING_MINIMUM_NOTICE
    )
