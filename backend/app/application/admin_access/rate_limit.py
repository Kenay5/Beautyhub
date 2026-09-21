"""Application boundary for administrative moving-window reservations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.domain.authentication.rate_limit import (
    ADMINISTRATIVE_RATE_LIMITS,
    AdministrativeRateLimitCategory,
    require_rate_limit_fingerprint,
)
from backend.app.domain.time import normalize_instant


class AdministrativeRateLimitStore(Protocol):
    """Atomically reserve an approved limit position without raw subjects."""

    def try_reserve(
        self,
        *,
        category: AdministrativeRateLimitCategory,
        subject_fingerprint: bytes,
        request_fingerprint: bytes,
        current_time: datetime,
        capacity: int,
        window: timedelta,
    ) -> bool:
        """Return false without an event when the moving window is exhausted."""


class ReserveAdministrativeRateLimit:
    """Reserve exactly one position for an internally identified request."""

    def __init__(self, *, store: AdministrativeRateLimitStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def reserve(
        self,
        *,
        category: AdministrativeRateLimitCategory,
        subject_fingerprint: bytes,
        request_fingerprint: bytes,
    ) -> bool:
        """Use the registered capacity and controlled clock for one request."""

        limit = ADMINISTRATIVE_RATE_LIMITS.get(category)
        if limit is None:
            raise ValueError("administrative rate limit category is invalid.")
        require_rate_limit_fingerprint(
            subject_fingerprint,
            field_name="subject",
        )
        require_rate_limit_fingerprint(
            request_fingerprint,
            field_name="request",
        )
        return self._store.try_reserve(
            category=category,
            subject_fingerprint=subject_fingerprint,
            request_fingerprint=request_fingerprint,
            current_time=normalize_instant(self._clock.now()),
            capacity=limit.capacity,
            window=limit.window,
        )
