"""T067 unit evidence for the shared public read request window."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.public_request_limit import (
    PUBLIC_READ_ACCEPTED_RESULT,
    LimitPublicReadRequests,
    PublicRequestRateLimitError,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
FINGERPRINT = b"synthetic-public-read-ip-fingerprint"


class InMemoryPublicRequestWindowStore:
    """Controlled moving window that stores synthetic fingerprints only."""

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


def test_t067_accepts_request_60_and_rejects_request_61_without_writing() -> None:
    store = InMemoryPublicRequestWindowStore()
    limiter = _limiter(store, NOW)

    for _ in range(60):
        limiter.ensure_allowed("service_catalog")

    with pytest.raises(PublicRequestRateLimitError):
        limiter.ensure_allowed("service_catalog")

    assert len(store.events) == 60
    assert {event[2] for event in store.events} == {PUBLIC_READ_ACCEPTED_RESULT}


def test_t067_catalog_and_availability_share_the_same_limit() -> None:
    store = InMemoryPublicRequestWindowStore()
    limiter = _limiter(store, NOW)

    for _ in range(30):
        limiter.ensure_allowed("service_catalog")
        limiter.ensure_allowed("availability")

    with pytest.raises(PublicRequestRateLimitError):
        limiter.ensure_allowed("availability")

    assert len(store.events) == 60


def test_t067_rejection_does_not_extend_window_and_exact_boundary_is_allowed() -> None:
    store = InMemoryPublicRequestWindowStore()
    limiter = _limiter(store, NOW)
    for _ in range(60):
        limiter.ensure_allowed("availability")

    with pytest.raises(PublicRequestRateLimitError):
        _limiter(store, NOW + timedelta(seconds=59)).ensure_allowed("availability")

    assert {event[4] for event in store.events} == {NOW + timedelta(seconds=60)}
    _limiter(store, NOW + timedelta(seconds=60)).ensure_allowed("availability")
    assert len(store.events) == 61


def test_t067_another_ip_has_an_independent_window() -> None:
    store = InMemoryPublicRequestWindowStore()
    limiter = _limiter(store, NOW)
    for _ in range(60):
        limiter.ensure_allowed("service_catalog")

    other = LimitPublicReadRequests(
        store=store,
        clock=FixedClock(NOW),
        subject_fingerprint=b"synthetic-other-public-read-ip-fingerprint",
    )

    other.ensure_allowed("service_catalog")
    assert len(store.events) == 61


def _limiter(
    store: InMemoryPublicRequestWindowStore,
    current_time: datetime,
) -> LimitPublicReadRequests:
    return LimitPublicReadRequests(
        store=store,
        clock=FixedClock(current_time),
        subject_fingerprint=FINGERPRINT,
    )
