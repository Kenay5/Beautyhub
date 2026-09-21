"""PostgreSQL adapter for atomic public request moving windows."""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import Connection, func, insert, select

from backend.app.application.public_request_limit import PublicRequestWindowStore
from backend.app.infrastructure.persistence.models import PublicRequestEvent


class PostgresPublicRequestWindowStore(PublicRequestWindowStore):
    """Serialize one subject/category window inside the caller transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

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
        """Count and append atomically; a rejected request creates no event."""

        self._connection.execute(
            select(func.pg_advisory_xact_lock(_lock_key(subject_fingerprint, category)))
        ).scalar_one()
        active_count = self._connection.execute(
            select(func.count())
            .select_from(PublicRequestEvent)
            .where(
                PublicRequestEvent.subject_fingerprint == subject_fingerprint,
                PublicRequestEvent.category == category,
                PublicRequestEvent.result == result,
                PublicRequestEvent.expires_at > current_time,
            )
        ).scalar_one()
        if active_count >= limit:
            return False

        self._connection.execute(
            insert(PublicRequestEvent).values(
                category=category,
                result=result,
                subject_fingerprint=subject_fingerprint,
                occurred_at=current_time,
                expires_at=expires_at,
            )
        )
        return True

    def find_active_denial_expiry(
        self,
        *,
        subject_fingerprint: bytes,
        category: str,
        result: str,
        current_time: datetime,
        limit: int,
    ) -> datetime | None:
        """Return the earliest expiry only when the moving window is exhausted."""

        active_count, earliest_expiry = self._connection.execute(
            select(
                func.count(),
                func.min(PublicRequestEvent.expires_at),
            ).where(
                PublicRequestEvent.subject_fingerprint == subject_fingerprint,
                PublicRequestEvent.category == category,
                PublicRequestEvent.result == result,
                PublicRequestEvent.expires_at > current_time,
            )
        ).one()
        if active_count < limit:
            return None
        return earliest_expiry


def _lock_key(subject_fingerprint: bytes, category: str) -> int:
    material = subject_fingerprint + b"\x00" + category.encode("ascii")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)
