"""Application boundary for administrative moving-window reservations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, Sequence

from backend.app.application.clock import Clock
from backend.app.domain.authentication.rate_limit import (
    ADMINISTRATIVE_RATE_LIMITS,
    AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT,
    AdministrativeRateLimitCategory,
    require_rate_limit_fingerprint,
)
from backend.app.domain.authentication.rate_limit import (
    AdministrativeRateLimitCategory,
)
from backend.app.application.entropy import SecretGenerator
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


@dataclass(frozen=True)
class AdministrativeRateLimitReservation:
    """One category/subject slot belonging to the same incoming action."""

    category: AdministrativeRateLimitCategory
    subject_fingerprint: bytes
    request_fingerprint: bytes
    current_time: datetime
    capacity: int
    window: timedelta


class CoordinatedAdministrativeRateLimitStore(Protocol):
    """Atomically reserve several moving-window slots in one transaction."""

    def try_reserve_many(
        self,
        *,
        reservations: Sequence[AdministrativeRateLimitReservation],
    ) -> "AdministrativeRateLimitReservationOutcome":
        """Reserve all requested categories or none of their capacity."""


@dataclass(frozen=True)
class AdministrativeRateLimitReservationOutcome:
    """Outcome for a coordinated request, including its internal denial reason."""

    allowed: bool
    denied_category: AdministrativeRateLimitCategory | None = None


class SecurityMessageActionBudget(Protocol):
    """Reserve one manually initiated security-message action for an account."""

    def reserve(self, *, account_id: int) -> bool:
        """Return false when the related account has exhausted its budget."""


class PublicSecurityMessageBudget(Protocol):
    """Coordinate the public IP and optional account budget for one request."""

    def reserve(self, *, account_id: int | None) -> bool:
        """Reserve public capacity and, when known, account capacity atomically."""


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


class ReserveCoordinatedAdministrativeRateLimits:
    """Reserve all applicable categories for one action without partial use."""

    def __init__(
        self,
        *,
        store: CoordinatedAdministrativeRateLimitStore,
        clock: Clock,
        secret_generator: SecretGenerator,
    ) -> None:
        self._store = store
        self._clock = clock
        self._secret_generator = secret_generator

    def reserve(
        self,
        *,
        limits: Sequence[
            tuple[AdministrativeRateLimitCategory, bytes]
        ],
    ) -> AdministrativeRateLimitReservationOutcome:
        """Check all moving windows and commit a single action fingerprint."""

        if not limits:
            raise ValueError("at least one administrative rate limit is required.")
        request_fingerprint = self._secret_generator.token_bytes(32)
        require_rate_limit_fingerprint(
            request_fingerprint,
            field_name="request",
        )
        current_time = normalize_instant(self._clock.now())
        reservations_by_key: dict[
            tuple[AdministrativeRateLimitCategory, bytes],
            AdministrativeRateLimitReservation,
        ] = {}
        for category, subject_fingerprint in limits:
            limit = ADMINISTRATIVE_RATE_LIMITS.get(category)
            if limit is None:
                raise ValueError("administrative rate limit category is invalid.")
            require_rate_limit_fingerprint(
                subject_fingerprint,
                field_name="subject",
            )
            key = (category, subject_fingerprint)
            reservations_by_key.setdefault(
                key,
                AdministrativeRateLimitReservation(
                    category=category,
                    subject_fingerprint=subject_fingerprint,
                    request_fingerprint=request_fingerprint,
                    current_time=current_time,
                    capacity=limit.capacity,
                    window=limit.window,
                ),
            )
        return self._store.try_reserve_many(
            reservations=tuple(reservations_by_key.values())
        )


class AuthenticatedAdministrativeRequestLimitError(PermissionError):
    """Raised when the authenticated account has exhausted its request budget."""


class LimitAuthenticatedAdministrativeRequests:
    """Reserve the common per-account budget before authenticated work begins."""

    def __init__(
        self,
        *,
        store: AdministrativeRateLimitStore,
        clock: Clock,
        subject_fingerprint: bytes,
        secret_generator: SecretGenerator,
    ) -> None:
        require_rate_limit_fingerprint(subject_fingerprint, field_name="subject")
        self._reserve = ReserveAdministrativeRateLimit(store=store, clock=clock)
        self._subject_fingerprint = subject_fingerprint
        self._secret_generator = secret_generator

    def ensure_allowed(self) -> None:
        """Persist one accepted operation; reject without downstream side effects."""

        allowed = self._reserve.reserve(
            category=AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
            subject_fingerprint=self._subject_fingerprint,
            request_fingerprint=self._secret_generator.token_bytes(32),
        )
        if not allowed:
            raise AuthenticatedAdministrativeRequestLimitError(
                "authenticated administrative request limit exceeded."
            )
