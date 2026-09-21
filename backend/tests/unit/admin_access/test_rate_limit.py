"""T015 unit evidence for approved administrative moving-window definitions."""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.domain.authentication.rate_limit import (
    ADMINISTRATIVE_RATE_LIMITS,
    AdministrativeRateLimitInvariantError,
    require_rate_limit_fingerprint,
)


def test_t015_exposes_only_the_four_approved_moving_limits() -> None:
    assert {
        category: (limit.capacity, limit.window)
        for category, limit in ADMINISTRATIVE_RATE_LIMITS.items()
    } == {
        "authentication_recovery_lost_factor": (20, timedelta(minutes=15)),
        "authenticated_administrative_operation": (120, timedelta(minutes=1)),
        "security_message_action": (10, timedelta(minutes=15)),
        "appointment_notification_operation": (30, timedelta(minutes=15)),
    }


@pytest.mark.parametrize("value", (b"", b"short", b"x" * 33))
def test_t015_rejects_non_digest_subjects_and_requests(value: bytes) -> None:
    with pytest.raises(AdministrativeRateLimitInvariantError):
        require_rate_limit_fingerprint(value, field_name="subject")
