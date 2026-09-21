"""Public availability calculation isolated from HTTP and PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.domain.schedule import (
    ScheduledInterval,
    TimeInterval,
    appointment_end,
    daily_start_times,
    has_neighbor_separation_conflict,
    has_schedule_conflict,
    occupying_intervals,
    validate_public_appointment_timing,
)
from backend.app.domain.service_configuration import validate_service_branch
from backend.app.domain.service_duration import validate_service_duration
from backend.app.domain.service_text import validate_service_text


class PublicAvailabilityValidationError(ValueError):
    """Raised when a public availability request cannot be fulfilled safely."""


class PublicAvailabilityReader(Protocol):
    """Read only the minimum schedule data required for public availability."""

    def get_active_service_duration(self, branch: str, service_name: str) -> int | None:
        """Return the duration of a service eligible at the selected branch."""

    def list_scheduled_intervals(self) -> Iterable[ScheduledInterval]:
        """Return appointments that still occupy the single professional."""

    def list_applicable_blocks(self, branch: str) -> Iterable[TimeInterval]:
        """Return global and selected-branch blocks without private metadata."""


class ListPublicAvailability:
    """Return only public starts that can currently be reserved."""

    def __init__(self, reader: PublicAvailabilityReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock

    def execute(
        self,
        *,
        branch: str,
        service_name: str,
        appointment_date: date,
    ) -> tuple[datetime, ...]:
        """Calculate bookable starts for one public service and business date."""

        normalized_branch = validate_service_branch(branch)
        normalized_service_name, _ = validate_service_text(service_name, None)
        if not isinstance(appointment_date, date) or isinstance(appointment_date, datetime):
            raise PublicAvailabilityValidationError("appointment date must be a date")

        duration_minutes = self._reader.get_active_service_duration(
            normalized_branch,
            normalized_service_name,
        )
        if duration_minutes is None:
            raise PublicAvailabilityValidationError("service is not publicly available")

        duration = timedelta(minutes=validate_service_duration(duration_minutes))
        scheduled_intervals = tuple(self._reader.list_scheduled_intervals())
        occupied_intervals = occupying_intervals(scheduled_intervals)
        blocks = tuple(self._reader.list_applicable_blocks(normalized_branch))
        current_time = self._clock.now()

        return tuple(
            start
            for start in daily_start_times(appointment_date)
            if self._is_available_start(
                start=start,
                duration=duration,
                branch=normalized_branch,
                current_time=current_time,
                scheduled_intervals=scheduled_intervals,
                occupied_intervals=occupied_intervals,
                blocks=blocks,
            )
        )

    @staticmethod
    def _is_available_start(
        *,
        start: datetime,
        duration: timedelta,
        branch: str,
        current_time: datetime,
        scheduled_intervals: tuple[ScheduledInterval, ...],
        occupied_intervals: tuple[TimeInterval, ...],
        blocks: tuple[TimeInterval, ...],
    ) -> bool:
        try:
            validate_public_appointment_timing(start, current_time)
        except ValueError:
            return False

        candidate = ScheduledInterval(
            interval=TimeInterval(start, appointment_end(start, duration)),
            branch=branch,
        )
        if has_schedule_conflict(candidate.interval, occupied_intervals):
            return False
        if any(candidate.interval.overlaps(block) for block in blocks):
            return False

        previous = max(
            (
                scheduled
                for scheduled in scheduled_intervals
                if scheduled.interval.end <= candidate.interval.start
            ),
            key=lambda scheduled: scheduled.interval.end,
            default=None,
        )
        following = min(
            (
                scheduled
                for scheduled in scheduled_intervals
                if scheduled.interval.start >= candidate.interval.end
            ),
            key=lambda scheduled: scheduled.interval.start,
            default=None,
        )
        return not has_neighbor_separation_conflict(candidate, previous, following)
