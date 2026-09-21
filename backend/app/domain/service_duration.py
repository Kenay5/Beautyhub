"""Pure validation for BeautyHub service durations."""

from __future__ import annotations


MIN_SERVICE_DURATION_MINUTES = 5
MAX_SERVICE_DURATION_MINUTES = 600
SERVICE_DURATION_INTERVAL_MINUTES = 5


class ServiceDurationValidationError(ValueError):
    """Raised when a service duration does not meet the approved domain rules."""


def validate_service_duration(duration_minutes: int) -> int:
    """Validate the service duration required by RF-01-CA-01 and CA-04."""

    if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int):
        raise ServiceDurationValidationError("duration must be an integer number of minutes.")

    if not MIN_SERVICE_DURATION_MINUTES <= duration_minutes <= MAX_SERVICE_DURATION_MINUTES:
        raise ServiceDurationValidationError(
            "duration must be between 5 and 600 minutes."
        )

    if duration_minutes % SERVICE_DURATION_INTERVAL_MINUTES != 0:
        raise ServiceDurationValidationError(
            "duration must be a multiple of 5 minutes."
        )

    return duration_minutes
