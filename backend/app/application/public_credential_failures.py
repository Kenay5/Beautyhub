"""Moving-window accounting for failed public appointment credentials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.domain.time import normalize_instant


PUBLIC_CREDENTIAL_EVENT_CATEGORY = "public_credential_validation"
PUBLIC_CREDENTIAL_FAILURE_RESULT = "failed"
PUBLIC_CREDENTIAL_BLOCK_RESULT = "blocked"
PUBLIC_CREDENTIAL_FAILURE_LIMIT = 5
PUBLIC_CREDENTIAL_FAILURE_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class PublicCredentialFailureResult:
    """The count recorded for one failure and an optional new block expiry."""

    failure_count: int
    block_expires_at: datetime | None


class PublicCredentialBlockedError(PublicRequestRateLimitError):
    """Reject a public credential operation while its IP block is active."""


class PublicCredentialFailureStore(Protocol):
    """Persist only the keyed IP fingerprint and minimum timing metadata."""

    def count_active_failures(
        self,
        *,
        subject_fingerprint: bytes,
        current_time: datetime,
    ) -> int:
        """Count failures that have not yet left the moving window."""

    def find_active_block_expiry(
        self,
        *,
        subject_fingerprint: bytes,
        current_time: datetime,
    ) -> datetime | None:
        """Return the latest active block expiry for the fingerprint, if any."""

    def append_event(
        self,
        *,
        subject_fingerprint: bytes,
        result: str,
        occurred_at: datetime,
        expires_at: datetime,
    ) -> None:
        """Persist a minimum-lived failure or block event."""


class RecordPublicCredentialFailure:
    """Record one failed public credential without retaining its plaintext values."""

    def __init__(
        self,
        *,
        store: PublicCredentialFailureStore,
        clock: Clock,
    ) -> None:
        self._store = store
        self._clock = clock

    def record_failure(self, *, subject_fingerprint: bytes) -> PublicCredentialFailureResult:
        """Create a block exactly when the fifth active failure is recorded."""

        _require_fingerprint(subject_fingerprint)
        current_time = normalize_instant(self._clock.now())
        _raise_when_blocked(
            store=self._store,
            subject_fingerprint=subject_fingerprint,
            current_time=current_time,
        )
        expires_at = current_time + PUBLIC_CREDENTIAL_FAILURE_WINDOW
        active_failures = self._store.count_active_failures(
            subject_fingerprint=subject_fingerprint,
            current_time=current_time,
        )
        failure_count = active_failures + 1
        self._store.append_event(
            subject_fingerprint=subject_fingerprint,
            result=PUBLIC_CREDENTIAL_FAILURE_RESULT,
            occurred_at=current_time,
            expires_at=expires_at,
        )
        if failure_count != PUBLIC_CREDENTIAL_FAILURE_LIMIT:
            return PublicCredentialFailureResult(
                failure_count=failure_count,
                block_expires_at=None,
            )

        self._store.append_event(
            subject_fingerprint=subject_fingerprint,
            result=PUBLIC_CREDENTIAL_BLOCK_RESULT,
            occurred_at=current_time,
            expires_at=expires_at,
        )
        return PublicCredentialFailureResult(
            failure_count=failure_count,
            block_expires_at=expires_at,
        )

    def record_success(self, *, subject_fingerprint: bytes) -> None:
        """Keep active failures intact; a success never resets the moving window."""

        _require_fingerprint(subject_fingerprint)


class EnsurePublicCredentialAccess:
    """Guard only public appointment lookup, modification, and cancellation."""

    def __init__(
        self,
        *,
        store: PublicCredentialFailureStore,
        clock: Clock,
    ) -> None:
        self._store = store
        self._clock = clock

    def ensure_allowed(self, *, subject_fingerprint: bytes) -> None:
        """Reject an active block without creating or extending any event."""

        _require_fingerprint(subject_fingerprint)
        _raise_when_blocked(
            store=self._store,
            subject_fingerprint=subject_fingerprint,
            current_time=normalize_instant(self._clock.now()),
        )


def _raise_when_blocked(
    *,
    store: PublicCredentialFailureStore,
    subject_fingerprint: bytes,
    current_time: datetime,
) -> None:
    if store.find_active_block_expiry(
        subject_fingerprint=subject_fingerprint,
        current_time=current_time,
    ) is not None:
        raise PublicCredentialBlockedError(
            "Public appointment credential access is temporarily blocked."
        )


def _require_fingerprint(subject_fingerprint: bytes) -> None:
    if not isinstance(subject_fingerprint, bytes) or not subject_fingerprint:
        raise ValueError("public credential subject fingerprint is invalid.")
