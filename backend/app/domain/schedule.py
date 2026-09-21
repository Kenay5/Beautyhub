"""Daily appointment-start grid rules for BeautyHub."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from backend.app.domain.service_configuration import validate_service_branch
from backend.app.domain.time import InstantValidationError, business_datetime, to_business_time


OPENING_TIME = time(hour=9)
LAST_START_TIME = time(hour=19)
START_INTERVAL = timedelta(minutes=15)
SAME_BRANCH_BUFFER = timedelta(minutes=5)
CROSS_BRANCH_BUFFER = timedelta(minutes=25)
PUBLIC_APPOINTMENT_MINIMUM_NOTICE = timedelta(minutes=60)
PUBLIC_APPOINTMENT_HORIZON = timedelta(days=90)
SCHEDULED_APPOINTMENT_STATUS = "scheduled"
FINAL_APPOINTMENT_STATUSES = frozenset(
    {"cancelled", "completed", "no_show", "unrecorded_result"},
)
APPOINTMENT_STATUSES = frozenset(
    {SCHEDULED_APPOINTMENT_STATUS, *FINAL_APPOINTMENT_STATUSES},
)


@dataclass(frozen=True)
class TimeInterval:
    """A business-time interval that includes its start and excludes its end."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        normalized_start = to_business_time(self.start)
        normalized_end = to_business_time(self.end)
        if normalized_end <= normalized_start:
            raise InstantValidationError("end must be after start")

        object.__setattr__(self, "start", normalized_start)
        object.__setattr__(self, "end", normalized_end)

    def contains(self, instant: datetime) -> bool:
        """Return whether an instant belongs to this semi-open interval."""

        normalized_instant = to_business_time(instant)
        return self.start <= normalized_instant < self.end

    def overlaps(self, other: TimeInterval) -> bool:
        """Return whether two semi-open intervals share an occupied instant."""

        if not isinstance(other, TimeInterval):
            raise InstantValidationError("other must be a TimeInterval")

        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class ScheduledInterval:
    """An occupied interval assigned to one approved BeautyHub branch."""

    interval: TimeInterval
    branch: str
    status: str = SCHEDULED_APPOINTMENT_STATUS

    def __post_init__(self) -> None:
        if not isinstance(self.interval, TimeInterval):
            raise InstantValidationError("interval must be a TimeInterval")

        object.__setattr__(self, "branch", validate_service_branch(self.branch))
        if not isinstance(self.status, str) or self.status not in APPOINTMENT_STATUSES:
            raise InstantValidationError("status must be an approved appointment status")


@dataclass(frozen=True)
class SameDayAlternativeSuggestion:
    """Available starts and whether the caller must ask for another date."""

    starts: tuple[datetime, ...]
    requires_different_date: bool


def occupying_intervals(
    appointments: tuple[ScheduledInterval, ...],
) -> tuple[TimeInterval, ...]:
    """Return intervals from appointments that still occupy the schedule."""

    return tuple(
        appointment.interval
        for appointment in appointments
        if appointment.status == SCHEDULED_APPOINTMENT_STATUS
    )


def has_schedule_conflict(
    candidate: TimeInterval,
    occupied_intervals: tuple[TimeInterval, ...],
) -> bool:
    """Return whether a candidate overlaps any occupied professional time."""

    return any(candidate.overlaps(occupied) for occupied in occupied_intervals)


def has_neighbor_separation_conflict(
    candidate: ScheduledInterval,
    previous: ScheduledInterval | None,
    following: ScheduledInterval | None,
) -> bool:
    """Return whether a candidate lacks required separation from either neighbor."""

    if previous is not None and candidate.interval.start < (
        previous.interval.end + required_separation(previous, candidate)
    ):
        return True

    return following is not None and following.interval.start < (
        candidate.interval.end + required_separation(candidate, following)
    )


def required_separation(
    first: ScheduledInterval,
    following: ScheduledInterval,
) -> timedelta:
    """Return the required buffer for two consecutive scheduled intervals."""

    if first.branch == following.branch:
        return SAME_BRANCH_BUFFER
    return CROSS_BRANCH_BUFFER


def earliest_same_branch_start(previous: TimeInterval) -> datetime:
    """Return the first 15-minute start after the same-branch buffer."""

    return next_grid_start_at_or_after(previous.end + SAME_BRANCH_BUFFER)


def has_same_branch_separation_conflict(
    previous: TimeInterval,
    candidate: TimeInterval,
) -> bool:
    """Return whether a following appointment lacks the required five minutes."""

    return candidate.start < previous.end + SAME_BRANCH_BUFFER


def earliest_cross_branch_start(previous: TimeInterval) -> datetime:
    """Return the first 15-minute start after the cross-branch buffer."""

    return next_grid_start_at_or_after(previous.end + CROSS_BRANCH_BUFFER)


def has_cross_branch_separation_conflict(
    previous: TimeInterval,
    candidate: TimeInterval,
) -> bool:
    """Return whether a following appointment lacks the required 25 minutes."""

    return candidate.start < previous.end + CROSS_BRANCH_BUFFER


def next_grid_start_at_or_after(instant: datetime) -> datetime:
    """Round an instant up to the next permitted 15-minute grid boundary."""

    normalized_instant = to_business_time(instant)
    minute_start = normalized_instant.replace(second=0, microsecond=0)
    minute_remainder = minute_start.minute % (START_INTERVAL.seconds // 60)

    if minute_remainder == 0 and normalized_instant == minute_start:
        return minute_start

    return minute_start + timedelta(minutes=15 - minute_remainder)


def appointment_end(start: datetime, duration: timedelta) -> datetime:
    """Return the business-zone end instant for an appointment window."""

    if not isinstance(duration, timedelta):
        raise InstantValidationError("duration must be a timedelta")
    if duration <= timedelta():
        raise InstantValidationError("duration must be positive")

    return to_business_time(start) + duration


def validate_public_appointment_timing(
    requested_start: datetime,
    current_time: datetime,
) -> None:
    """Validate public timing before checking schedule availability."""

    normalized_requested_start = to_business_time(requested_start)
    normalized_current_time = to_business_time(current_time)

    if normalized_requested_start < (
        normalized_current_time + PUBLIC_APPOINTMENT_MINIMUM_NOTICE
    ):
        raise InstantValidationError("public appointment requires at least 60 minutes notice")
    if normalized_requested_start > normalized_current_time + PUBLIC_APPOINTMENT_HORIZON:
        raise InstantValidationError("public appointment exceeds the 90-day horizon")
    validate_daily_start(normalized_requested_start, "public appointment")


def earliest_administrative_start(current_time: datetime) -> datetime:
    """Return the first daily appointment start that is not before current time."""

    normalized_current_time = to_business_time(current_time)
    for start in daily_start_times(normalized_current_time.date()):
        if start >= normalized_current_time:
            return start

    next_date = normalized_current_time.date() + timedelta(days=1)
    return daily_start_times(next_date)[0]


def validate_administrative_appointment_timing(
    requested_start: datetime,
    current_time: datetime,
) -> None:
    """Validate the approved administrative immediate-start boundaries."""

    normalized_requested_start = to_business_time(requested_start)
    normalized_current_time = to_business_time(current_time)

    if normalized_requested_start < normalized_current_time:
        raise InstantValidationError("administrative appointment cannot start in the past")
    if normalized_requested_start > normalized_current_time + PUBLIC_APPOINTMENT_HORIZON:
        raise InstantValidationError("administrative appointment exceeds the 90-day horizon")
    validate_daily_start(normalized_requested_start, "administrative appointment")


def validate_daily_start(requested_start: datetime, appointment_kind: str) -> None:
    """Validate business hours and the approved daily start grid."""

    requested_time = requested_start.timetz().replace(tzinfo=None)
    if requested_time < OPENING_TIME or requested_time > LAST_START_TIME:
        raise InstantValidationError(f"{appointment_kind} must start during business hours")
    if requested_start not in daily_start_times(requested_start.date()):
        raise InstantValidationError(
            f"{appointment_kind} must start on the approved daily grid",
        )


def nearest_same_day_alternatives(
    requested_start: datetime,
    available_starts: tuple[datetime, ...],
) -> tuple[datetime, ...]:
    """Return at most three available starts nearest to the requested start."""

    normalized_requested_start = to_business_time(requested_start)
    same_day_starts = tuple(
        normalized_start
        for start in available_starts
        if (normalized_start := to_business_time(start)).date()
        == normalized_requested_start.date()
        and normalized_start != normalized_requested_start
    )

    starts_with_later_ties_first = sorted(same_day_starts, reverse=True)
    return tuple(
        sorted(
            starts_with_later_ties_first,
            key=lambda start: abs(start - normalized_requested_start),
        )[:3],
    )


def same_day_alternative_suggestion(
    requested_start: datetime,
    available_starts: tuple[datetime, ...],
) -> SameDayAlternativeSuggestion:
    """Return nearby starts or signal that the caller must request another date."""

    starts = nearest_same_day_alternatives(requested_start, available_starts)
    return SameDayAlternativeSuggestion(
        starts=starts,
        requires_different_date=not starts,
    )


def public_same_day_alternative_suggestion(
    requested_start: datetime,
    current_time: datetime,
    available_starts: tuple[datetime, ...],
) -> SameDayAlternativeSuggestion:
    """Suggest alternatives only after public timing validation succeeds."""

    validate_public_appointment_timing(requested_start, current_time)
    return same_day_alternative_suggestion(requested_start, available_starts)


def administrative_same_day_alternative_suggestion(
    requested_start: datetime,
    current_time: datetime,
    available_starts: tuple[datetime, ...],
) -> SameDayAlternativeSuggestion:
    """Suggest alternatives only after administrative timing validation succeeds."""

    validate_administrative_appointment_timing(requested_start, current_time)
    return same_day_alternative_suggestion(requested_start, available_starts)


def daily_start_times(local_date: date) -> tuple[datetime, ...]:
    """Return every permitted appointment start for one business date."""

    current_start = business_datetime(local_date, OPENING_TIME)
    last_start = business_datetime(local_date, LAST_START_TIME)
    starts: list[datetime] = []

    while current_start <= last_start:
        starts.append(current_start)
        current_start += START_INTERVAL

    return tuple(starts)
