"""PostgreSQL persistence for administrative moving-window limits."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert

from backend.app.application.admin_access.rate_limit import AdministrativeRateLimitStore
from backend.app.application.admin_access.rate_limit import (
    AdministrativeRateLimitReservation,
    AdministrativeRateLimitReservationOutcome,
    CoordinatedAdministrativeRateLimitStore,
)
from backend.app.domain.authentication.rate_limit import AdministrativeRateLimitCategory
from backend.app.infrastructure.persistence.models import RateLimitEvent, RateLimitGuard


class PostgresAdministrativeRateLimitStore(
    AdministrativeRateLimitStore,
    CoordinatedAdministrativeRateLimitStore,
):
    """Serialize each category and opaque subject through one guard row."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

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
        """Preserve an idempotent reservation or reject without a new event."""

        return self.try_reserve_many(
            reservations=(
                AdministrativeRateLimitReservation(
                    category=category,
                    subject_fingerprint=subject_fingerprint,
                    request_fingerprint=request_fingerprint,
                    current_time=current_time,
                    capacity=capacity,
                    window=window,
                ),
            )
        ).allowed

    def try_reserve_many(
        self,
        *,
        reservations: tuple[AdministrativeRateLimitReservation, ...]
        | list[AdministrativeRateLimitReservation],
    ) -> AdministrativeRateLimitReservationOutcome:
        """Lock, preflight, and then write every budget event atomically."""

        if not reservations:
            raise ValueError("at least one administrative rate reservation is required.")

        unique: dict[
            tuple[str, bytes], AdministrativeRateLimitReservation
        ] = {}
        for reservation in reservations:
            key = (reservation.category, reservation.subject_fingerprint)
            existing = unique.get(key)
            if existing is not None and existing != reservation:
                raise ValueError("duplicate administrative rate limit is inconsistent.")
            unique[key] = reservation

        ordered = tuple(
            unique[key]
            for key in sorted(unique, key=lambda item: (item[0], item[1]))
        )
        for reservation in ordered:
            self._ensure_and_lock_guard(
                category=reservation.category,
                subject_fingerprint=reservation.subject_fingerprint,
            )

        pending: list[AdministrativeRateLimitReservation] = []
        for reservation in ordered:
            existing = self._connection.execute(
                select(RateLimitEvent.rate_limit_event_id).where(
                    RateLimitEvent.category == reservation.category,
                    RateLimitEvent.subject_fingerprint
                    == reservation.subject_fingerprint,
                    RateLimitEvent.request_fingerprint
                    == reservation.request_fingerprint,
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue

            active_count = self._connection.execute(
                select(func.count())
                .select_from(RateLimitEvent)
                .where(
                    RateLimitEvent.category == reservation.category,
                    RateLimitEvent.subject_fingerprint
                    == reservation.subject_fingerprint,
                    RateLimitEvent.occurred_at
                    > reservation.current_time - reservation.window,
                )
            ).scalar_one()
            if active_count >= reservation.capacity:
                return AdministrativeRateLimitReservationOutcome(
                    allowed=False,
                    denied_category=reservation.category,
                )
            pending.append(reservation)

        for reservation in pending:
            self._connection.execute(
                insert(RateLimitEvent).values(
                    category=reservation.category,
                    subject_fingerprint=reservation.subject_fingerprint,
                    request_fingerprint=reservation.request_fingerprint,
                    occurred_at=reservation.current_time,
                )
            )
        return AdministrativeRateLimitReservationOutcome(allowed=True)

    def _ensure_and_lock_guard(
        self,
        *,
        category: AdministrativeRateLimitCategory,
        subject_fingerprint: bytes,
    ) -> None:
        self._connection.execute(
            insert(RateLimitGuard)
            .values(category=category, subject_fingerprint=subject_fingerprint)
            .on_conflict_do_nothing(
                index_elements=(
                    RateLimitGuard.category,
                    RateLimitGuard.subject_fingerprint,
                )
            )
        )
        self._connection.execute(
            select(RateLimitGuard.rate_limit_guard_id)
            .where(
                RateLimitGuard.category == category,
                RateLimitGuard.subject_fingerprint == subject_fingerprint,
            )
            .with_for_update()
        ).scalar_one()
