"""T069 unit evidence for overlapping public access restrictions."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.public_access_restrictions import (
    CombinePublicAppointmentRestrictions,
)
from backend.app.application.public_credential_failures import (
    PUBLIC_CREDENTIAL_BLOCK_RESULT,
    PUBLIC_CREDENTIAL_FAILURE_RESULT,
)
from backend.app.application.public_request_limit import (
    PUBLIC_APPOINTMENT_EVENT_CATEGORY,
    PUBLIC_READ_ACCEPTED_RESULT,
    PublicRequestRateLimitError,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 10, 10, tzinfo=BUSINESS_TIME_ZONE)
FINGERPRINT = b"synthetic-combined-public-ip-fingerprint"


class InMemoryCombinedRestrictionStore:
    """Controlled store containing only synthetic fingerprints and timings."""

    def __init__(self) -> None:
        self.request_events: list[tuple[bytes, str, str, datetime, datetime]] = []
        self.credential_events: list[tuple[bytes, str, datetime, datetime]] = []

    def find_active_denial_expiry(
        self,
        *,
        subject_fingerprint: bytes,
        category: str,
        result: str,
        current_time: datetime,
        limit: int,
    ) -> datetime | None:
        active_expiries = sorted(
            expires_at
            for fingerprint, stored_category, stored_result, _, expires_at
            in self.request_events
            if fingerprint == subject_fingerprint
            and stored_category == category
            and stored_result == result
            and expires_at > current_time
        )
        if len(active_expiries) < limit:
            return None
        return active_expiries[0]

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
        if self.find_active_denial_expiry(
            subject_fingerprint=subject_fingerprint,
            category=category,
            result=result,
            current_time=current_time,
            limit=limit,
        ) is not None:
            return False
        self.request_events.append(
            (subject_fingerprint, category, result, current_time, expires_at)
        )
        return True

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
            for fingerprint, result, _, expires_at in self.credential_events
        )

    def find_active_block_expiry(
        self,
        *,
        subject_fingerprint: bytes,
        current_time: datetime,
    ) -> datetime | None:
        active_expiries = [
            expires_at
            for fingerprint, result, _, expires_at in self.credential_events
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
        self.credential_events.append(
            (subject_fingerprint, result, occurred_at, expires_at)
        )


def test_t069_credential_block_wins_when_it_expires_later() -> None:
    store = InMemoryCombinedRestrictionStore()
    _fill_general_limit(store, expires_at=NOW + timedelta(minutes=5))
    _add_credential_block(store, expires_at=NOW + timedelta(minutes=10))

    with pytest.raises(PublicRequestRateLimitError) as raised:
        _guard(store).ensure_allowed("appointment_lookup")

    assert raised.value.denied_until == NOW + timedelta(minutes=10)
    assert len(store.request_events) == 10


def test_t069_general_limit_wins_when_it_expires_later() -> None:
    store = InMemoryCombinedRestrictionStore()
    _fill_general_limit(store, expires_at=NOW + timedelta(minutes=10))
    _add_credential_block(store, expires_at=NOW + timedelta(minutes=5))

    with pytest.raises(PublicRequestRateLimitError) as raised:
        _guard(store).ensure_allowed("appointment_modification")

    assert raised.value.denied_until == NOW + timedelta(minutes=10)
    assert len(store.request_events) == 10


def test_t069_active_credential_block_does_not_consume_general_capacity() -> None:
    store = InMemoryCombinedRestrictionStore()
    _add_credential_block(store, expires_at=NOW + timedelta(minutes=5))

    with pytest.raises(PublicRequestRateLimitError):
        _guard(store).ensure_allowed("appointment_cancellation")

    assert store.request_events == []


def test_t069_expired_restrictions_do_not_deny_or_extend_their_windows() -> None:
    store = InMemoryCombinedRestrictionStore()
    _fill_general_limit(store, expires_at=NOW)
    _add_credential_block(store, expires_at=NOW)

    _guard(store).ensure_allowed("appointment_lookup")

    assert len(store.request_events) == 11
    assert store.request_events[-1][4] == NOW + timedelta(minutes=15)


def _guard(
    store: InMemoryCombinedRestrictionStore,
) -> CombinePublicAppointmentRestrictions:
    return CombinePublicAppointmentRestrictions(
        request_store=store,
        credential_store=store,
        clock=FixedClock(NOW),
        subject_fingerprint=FINGERPRINT,
    )


def _fill_general_limit(
    store: InMemoryCombinedRestrictionStore,
    *,
    expires_at: datetime,
) -> None:
    store.request_events.extend(
        (
            FINGERPRINT,
            PUBLIC_APPOINTMENT_EVENT_CATEGORY,
            PUBLIC_READ_ACCEPTED_RESULT,
            NOW - timedelta(minutes=5),
            expires_at,
        )
        for _ in range(10)
    )


def _add_credential_block(
    store: InMemoryCombinedRestrictionStore,
    *,
    expires_at: datetime,
) -> None:
    store.credential_events.append(
        (
            FINGERPRINT,
            PUBLIC_CREDENTIAL_BLOCK_RESULT,
            NOW - timedelta(minutes=5),
            expires_at,
        )
    )
