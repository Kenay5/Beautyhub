"""Unit tests for service duration validation."""

import pytest

from backend.app.domain.service_duration import (
    ServiceDurationValidationError,
    validate_service_duration,
)


@pytest.mark.parametrize("duration_minutes", [5, 60, 600])
def test_service_duration_accepts_approved_range_and_interval(
    duration_minutes: int,
) -> None:
    assert validate_service_duration(duration_minutes) == duration_minutes


@pytest.mark.parametrize("duration_minutes", [4, 601])
def test_service_duration_rejects_values_outside_the_approved_range(
    duration_minutes: int,
) -> None:
    with pytest.raises(ServiceDurationValidationError, match="between 5 and 600"):
        validate_service_duration(duration_minutes)


@pytest.mark.parametrize("duration_minutes", [6, 599])
def test_service_duration_rejects_values_outside_the_five_minute_interval(
    duration_minutes: int,
) -> None:
    with pytest.raises(ServiceDurationValidationError, match="multiple of 5"):
        validate_service_duration(duration_minutes)


@pytest.mark.parametrize("duration_value", [True, 5.0, "5"])
def test_service_duration_rejects_non_integer_values(duration_value: object) -> None:
    with pytest.raises(ServiceDurationValidationError, match="integer"):
        validate_service_duration(duration_value)  # type: ignore[arg-type]
