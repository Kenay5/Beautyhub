"""T066 unit evidence for applying and expiring credential blocks."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.public_credential_failures import (
    PUBLIC_CREDENTIAL_BLOCK_RESULT,
    PUBLIC_CREDENTIAL_FAILURE_RESULT,
    EnsurePublicCredentialAccess,
    PublicCredentialBlockedError,
    RecordPublicCredentialFailure,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
BLOCKED_FINGERPRINT = b"synthetic-blocked-ip-fingerprint"
OTHER_FINGERPRINT = b"synthetic-other-ip-fingerprint"


class InMemoryCredentialProtectionStore:
    """Controlled store that retains synthetic fingerprints only."""

    def __init__(self) -> None:
        self.events: list[tuple[bytes, str, datetime, datetime]] = []

    def count_active_failures(
        self,
        *,
        subject_fingerprint: bytes,
        current_time: datetime,
    ) -> int:
        return sum(
            fingerprint == subject_fingerprint
            and result == PUBLIC_CREDENTIAL_FAILURE_RESULT
            and expires_at > current_time
            for fingerprint, result, _, expires_at in self.events
        )

    def find_active_block_expiry(
        self,
        *,
        subject_fingerprint: bytes,
        current_time: datetime,
    ) -> datetime | None:
        active_expiries = [
            expires_at
            for fingerprint, result, _, expires_at in self.events
            if fingerprint == subject_fingerprint
            and result == PUBLIC_CREDENTIAL_BLOCK_RESULT
            and expires_at > current_time
        ]
        return max(active_expiries, default=None)

    def append_event(
        self,
        *,
        subject_fingerprint: bytes,
        result: str,
        occurred_at: datetime,
        expires_at: datetime,
    ) -> None:
        self.events.append((subject_fingerprint, result, occurred_at, expires_at))


def test_t066_active_block_rejects_without_incrementing_or_extending_it() -> None:
    store = _store_with_block()
    original_events = tuple(store.events)
    original_expiry = NOW + timedelta(minutes=15)
    blocked_recorder = RecordPublicCredentialFailure(
        store=store,
        clock=FixedClock(NOW + timedelta(minutes=1)),
    )

    with pytest.raises(PublicCredentialBlockedError):
        blocked_recorder.record_failure(subject_fingerprint=BLOCKED_FINGERPRINT)

    assert tuple(store.events) == original_events
    assert store.find_active_block_expiry(
        subject_fingerprint=BLOCKED_FINGERPRINT,
        current_time=NOW + timedelta(minutes=1),
    ) == original_expiry


def test_t066_block_applies_until_but_not_at_its_exact_expiry() -> None:
    store = _store_with_block()
    before_expiry = EnsurePublicCredentialAccess(
        store=store,
        clock=FixedClock(NOW + timedelta(minutes=14, seconds=59, microseconds=999999)),
    )
    at_expiry = EnsurePublicCredentialAccess(
        store=store,
        clock=FixedClock(NOW + timedelta(minutes=15)),
    )

    with pytest.raises(PublicCredentialBlockedError):
        before_expiry.ensure_allowed(subject_fingerprint=BLOCKED_FINGERPRINT)

    at_expiry.ensure_allowed(subject_fingerprint=BLOCKED_FINGERPRINT)


def test_t066_blocked_ip_does_not_affect_another_ip() -> None:
    store = _store_with_block()
    guard = EnsurePublicCredentialAccess(
        store=store,
        clock=FixedClock(NOW + timedelta(minutes=1)),
    )

    with pytest.raises(PublicCredentialBlockedError):
        guard.ensure_allowed(subject_fingerprint=BLOCKED_FINGERPRINT)

    guard.ensure_allowed(subject_fingerprint=OTHER_FINGERPRINT)


def _store_with_block() -> InMemoryCredentialProtectionStore:
    store = InMemoryCredentialProtectionStore()
    recorder = RecordPublicCredentialFailure(store=store, clock=FixedClock(NOW))
    for _ in range(5):
        recorder.record_failure(subject_fingerprint=BLOCKED_FINGERPRINT)
    return store
