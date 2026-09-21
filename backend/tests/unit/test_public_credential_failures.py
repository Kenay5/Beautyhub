"""T065 unit evidence for public credential failure windows."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.application.clock import FixedClock
from backend.app.application.public_credential_failures import (
    PUBLIC_CREDENTIAL_BLOCK_RESULT,
    PUBLIC_CREDENTIAL_FAILURE_RESULT,
    RecordPublicCredentialFailure,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
FINGERPRINT = b"synthetic-ip-fingerprint"


class InMemoryFailureStore:
    """Controlled event store holding only synthetic fingerprints."""

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


def test_t065_blocks_exactly_on_the_fifth_failure_for_fifteen_minutes() -> None:
    store = InMemoryFailureStore()
    recorder = _recorder(store, NOW)

    first_four = tuple(recorder.record_failure(subject_fingerprint=FINGERPRINT) for _ in range(4))
    fifth = recorder.record_failure(subject_fingerprint=FINGERPRINT)

    assert [result.failure_count for result in first_four] == [1, 2, 3, 4]
    assert all(result.block_expires_at is None for result in first_four)
    assert fifth.failure_count == 5
    assert fifth.block_expires_at == NOW + timedelta(minutes=15)
    assert [event[1] for event in store.events] == [
        PUBLIC_CREDENTIAL_FAILURE_RESULT,
        PUBLIC_CREDENTIAL_FAILURE_RESULT,
        PUBLIC_CREDENTIAL_FAILURE_RESULT,
        PUBLIC_CREDENTIAL_FAILURE_RESULT,
        PUBLIC_CREDENTIAL_FAILURE_RESULT,
        PUBLIC_CREDENTIAL_BLOCK_RESULT,
    ]


def test_t065_a_success_does_not_remove_active_failures() -> None:
    store = InMemoryFailureStore()
    recorder = _recorder(store, NOW)
    for _ in range(4):
        recorder.record_failure(subject_fingerprint=FINGERPRINT)

    recorder.record_success(subject_fingerprint=FINGERPRINT)
    fifth = recorder.record_failure(subject_fingerprint=FINGERPRINT)

    assert fifth.failure_count == 5
    assert fifth.block_expires_at == NOW + timedelta(minutes=15)
    assert len(store.events) == 6


def test_t065_failure_at_the_exact_window_boundary_no_longer_counts() -> None:
    store = InMemoryFailureStore()
    first = _recorder(store, NOW)
    first.record_failure(subject_fingerprint=FINGERPRINT)
    at_boundary = _recorder(store, NOW + timedelta(minutes=15))

    results = tuple(
        at_boundary.record_failure(subject_fingerprint=FINGERPRINT)
        for _ in range(4)
    )

    assert [result.failure_count for result in results] == [1, 2, 3, 4]
    assert all(result.block_expires_at is None for result in results)


def test_t065_failure_one_second_before_the_window_boundary_still_counts() -> None:
    store = InMemoryFailureStore()
    first = _recorder(store, NOW)
    first.record_failure(subject_fingerprint=FINGERPRINT)
    before_boundary = _recorder(store, NOW + timedelta(minutes=14, seconds=59))

    results = tuple(
        before_boundary.record_failure(subject_fingerprint=FINGERPRINT)
        for _ in range(4)
    )

    assert results[-1].failure_count == 5
    assert results[-1].block_expires_at == NOW + timedelta(minutes=29, seconds=59)


def _recorder(
    store: InMemoryFailureStore,
    current_time: datetime,
) -> RecordPublicCredentialFailure:
    return RecordPublicCredentialFailure(store=store, clock=FixedClock(current_time))
