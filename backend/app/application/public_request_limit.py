"""Application rules for bounded public request windows."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.domain.time import normalize_instant


PUBLIC_READ_CATEGORIES = frozenset({"service_catalog", "availability"})
PUBLIC_READ_EVENT_CATEGORY = "catalog_availability"
PUBLIC_READ_ACCEPTED_RESULT = "accepted"
PUBLIC_READ_REQUEST_LIMIT = 60
PUBLIC_READ_REQUEST_WINDOW = timedelta(seconds=60)
PUBLIC_APPOINTMENT_OPERATION_CATEGORIES = frozenset(
    {
        "appointment_confirmation",
        "appointment_lookup",
        "appointment_modification",
        "appointment_cancellation",
    }
)
PUBLIC_APPOINTMENT_EVENT_CATEGORY = "appointment_operation"
PUBLIC_APPOINTMENT_REQUEST_LIMIT = 10
PUBLIC_APPOINTMENT_REQUEST_WINDOW = timedelta(minutes=15)


class PublicRequestRateLimitError(ValueError):
    """Raised when an approved public request limit denies an operation."""

    def __init__(
        self,
        message: str,
        *,
        denied_until: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.denied_until = denied_until


class PublicRequestLimiter(Protocol):
    """Check a named public operation before it accesses business data."""

    def ensure_allowed(self, category: str) -> None:
        """Raise PublicRequestRateLimitError when this request is denied."""


class AllowPublicRequests:
    """Temporary composition adapter until T068 adds PostgreSQL-backed windows."""

    def ensure_allowed(self, category: str) -> None:
        """Allow the request while preserving the approved error boundary."""


class PublicRequestWindowStore(Protocol):
    """Atomically reserve one position in a persisted moving window."""

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
        """Return false without writing when the active limit is exhausted."""

    def find_active_denial_expiry(
        self,
        *,
        subject_fingerprint: bytes,
        category: str,
        result: str,
        current_time: datetime,
        limit: int,
    ) -> datetime | None:
        """Return when an exhausted active window first allows another request."""


class LimitPublicReadRequests:
    """Share the 60-per-minute limit across catalog and availability reads."""

    def __init__(
        self,
        *,
        store: PublicRequestWindowStore,
        clock: Clock,
        subject_fingerprint: bytes,
    ) -> None:
        if not isinstance(subject_fingerprint, bytes) or not subject_fingerprint:
            raise ValueError("public request subject fingerprint is invalid.")
        self._store = store
        self._clock = clock
        self._subject_fingerprint = subject_fingerprint

    def ensure_allowed(self, category: str) -> None:
        """Record an accepted read or reject without changing its window."""

        if category not in PUBLIC_READ_CATEGORIES:
            raise ValueError("public read request category is invalid.")
        current_time = normalize_instant(self._clock.now())
        accepted = self._store.try_record_request(
            subject_fingerprint=self._subject_fingerprint,
            category=PUBLIC_READ_EVENT_CATEGORY,
            result=PUBLIC_READ_ACCEPTED_RESULT,
            current_time=current_time,
            expires_at=current_time + PUBLIC_READ_REQUEST_WINDOW,
            limit=PUBLIC_READ_REQUEST_LIMIT,
        )
        if not accepted:
            raise PublicRequestRateLimitError(
                "Public catalog and availability request limit exceeded."
            )


class LimitPublicAppointmentRequests:
    """Share the 10-per-15-minute limit across public appointment operations."""

    def __init__(
        self,
        *,
        store: PublicRequestWindowStore,
        clock: Clock,
        subject_fingerprint: bytes,
    ) -> None:
        if not isinstance(subject_fingerprint, bytes) or not subject_fingerprint:
            raise ValueError("public request subject fingerprint is invalid.")
        self._store = store
        self._clock = clock
        self._subject_fingerprint = subject_fingerprint

    def ensure_allowed(self, category: str) -> None:
        """Record an accepted appointment operation or reject without a write."""

        if category not in PUBLIC_APPOINTMENT_OPERATION_CATEGORIES:
            raise ValueError("public appointment request category is invalid.")
        current_time = normalize_instant(self._clock.now())
        accepted = self._store.try_record_request(
            subject_fingerprint=self._subject_fingerprint,
            category=PUBLIC_APPOINTMENT_EVENT_CATEGORY,
            result=PUBLIC_READ_ACCEPTED_RESULT,
            current_time=current_time,
            expires_at=current_time + PUBLIC_APPOINTMENT_REQUEST_WINDOW,
            limit=PUBLIC_APPOINTMENT_REQUEST_LIMIT,
        )
        if not accepted:
            raise PublicRequestRateLimitError(
                "Public appointment request limit exceeded."
            )
