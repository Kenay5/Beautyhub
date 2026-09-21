"""T068 unit evidence for public appointment request limits."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.public_request_limit import (
    PUBLIC_READ_ACCEPTED_RESULT,
    LimitPublicAppointmentRequests,
    PublicRequestRateLimitError,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
FINGERPRINT = b"synthetic-public-appointment-ip-fingerprint"


class InMemoryPublicAppointmentWindowStore:
    """Controlled store that retains only synthetic fingerprints."""

    def __init__(self) -> None:
        self.events: list[tuple[bytes, str, str, datetime, datetime]] = []

    def try_record_request(
        self,
        *,
        subject_fingerprint: bytes,
        category: str,
        result: str,
        current_time: datetime,
        expires_at: datetime,
        limit: int,
    ) -> bool:
        active_count = sum(
            fingerprint == subject_fingerprint
            and stored_category == category
            and stored_result == result
            and stored_expiry > current_time
            for (
                fingerprint,
                stored_category,
                stored_result,
                _,
                stored_expiry,
            ) in self.events
        )
        if active_count >= limit:
            return False
        self.events.append(
            (subject_fingerprint, category, result, current_time, expires_at)
        )
        return True


def test_t068_accepts_operation_10_and_rejects_operation_11_without_writing() -> None:
    store = InMemoryPublicAppointmentWindowStore()
    limiter = _limiter(store, NOW)

    for _ in range(10):
        limiter.ensure_allowed("appointment_confirmation")

    with pytest.raises(PublicRequestRateLimitError):
        limiter.ensure_allowed("appointment_confirmation")

    assert len(store.events) == 10
    assert {event[2] for event in store.events} == {PUBLIC_READ_ACCEPTED_RESULT}


def test_t068_future_public_operations_share_the_same_window() -> None:
    store = InMemoryPublicAppointmentWindowStore()
    limiter = _limiter(store, NOW)

    categories = (
        "appointment_confirmation",
        "appointment_lookup",
        "appointment_modification",
        "appointment_cancellation",
        "appointment_confirmation",
        "appointment_lookup",
        "appointment_modification",
        "appointment_cancellation",
        "appointment_confirmation",
        "appointment_lookup",
    )
    for category in categories:
        limiter.ensure_allowed(category)

    with pytest.raises(PublicRequestRateLimitError):
        limiter.ensure_allowed("appointment_cancellation")

    assert len(store.events) == 10


def test_t068_rejection_does_not_extend_window_and_exact_boundary_is_allowed() -> None:
    store = InMemoryPublicAppointmentWindowStore()
    limiter = _limiter(store, NOW)
    for _ in range(10):
        limiter.ensure_allowed("appointment_confirmation")

    with pytest.raises(PublicRequestRateLimitError):
        _limiter(store, NOW + timedelta(minutes=14, seconds=59)).ensure_allowed(
            "appointment_confirmation"
        )

    assert {event[4] for event in store.events} == {NOW + timedelta(minutes=15)}
    _limiter(store, NOW + timedelta(minutes=15)).ensure_allowed(
        "appointment_confirmation"
    )
    assert len(store.events) == 11


def test_t068_another_ip_has_an_independent_window() -> None:
    store = InMemoryPublicAppointmentWindowStore()
    limiter = _limiter(store, NOW)
    for _ in range(10):
        limiter.ensure_allowed("appointment_confirmation")

    other = LimitPublicAppointmentRequests(
        store=store,
        clock=FixedClock(NOW),
        subject_fingerprint=b"synthetic-other-public-appointment-ip-fingerprint",
    )

    other.ensure_allowed("appointment_confirmation")
    assert len(store.events) == 11


def _limiter(
    store: InMemoryPublicAppointmentWindowStore,
    current_time: datetime,
) -> LimitPublicAppointmentRequests:
    return LimitPublicAppointmentRequests(
        store=store,
        clock=FixedClock(current_time),
        subject_fingerprint=FINGERPRINT,
    )
