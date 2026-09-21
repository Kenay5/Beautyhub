"""PostgreSQL persistence for administrative moving-window limits."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert

from backend.app.application.admin_access.rate_limit import AdministrativeRateLimitStore
from backend.app.domain.authentication.rate_limit import AdministrativeRateLimitCategory
from backend.app.infrastructure.persistence.models import RateLimitEvent, RateLimitGuard


class PostgresAdministrativeRateLimitStore(AdministrativeRateLimitStore):
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

        self._ensure_and_lock_guard(
            category=category,
            subject_fingerprint=subject_fingerprint,
        )
        existing = self._connection.execute(
            select(RateLimitEvent.rate_limit_event_id).where(
                RateLimitEvent.category == category,
                RateLimitEvent.subject_fingerprint == subject_fingerprint,
                RateLimitEvent.request_fingerprint == request_fingerprint,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return True

        active_count = self._connection.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.category == category,
                RateLimitEvent.subject_fingerprint == subject_fingerprint,
                RateLimitEvent.occurred_at > current_time - window,
            )
        ).scalar_one()
        if active_count >= capacity:
            return False

        self._connection.execute(
            insert(RateLimitEvent).values(
                category=category,
                subject_fingerprint=subject_fingerprint,
                request_fingerprint=request_fingerprint,
                occurred_at=current_time,
            )
        )
        return True

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
