"""PostgreSQL persistence for public credential failure windows."""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import Connection, func, insert, select

from backend.app.application.public_credential_failures import (
    PUBLIC_CREDENTIAL_BLOCK_RESULT,
    PUBLIC_CREDENTIAL_EVENT_CATEGORY,
    PUBLIC_CREDENTIAL_FAILURE_RESULT,
    PublicCredentialFailureStore,
)
from backend.app.infrastructure.persistence.models import PublicRequestEvent


class PostgresPublicCredentialFailureStore(PublicCredentialFailureStore):
    """Store keyed credential failure events without raw IPs or credentials."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def count_active_failures(
        self,
        *,
        subject_fingerprint: bytes,
        current_time: datetime,
    ) -> int:
        """Count only failures whose 15-minute retention has not expired."""

        return self._connection.execute(
            select(func.count())
            .select_from(PublicRequestEvent)
            .where(
                PublicRequestEvent.subject_fingerprint == subject_fingerprint,
                PublicRequestEvent.category == PUBLIC_CREDENTIAL_EVENT_CATEGORY,
                PublicRequestEvent.result == PUBLIC_CREDENTIAL_FAILURE_RESULT,
                PublicRequestEvent.expires_at > current_time,
            )
        ).scalar_one()

    def find_active_block_expiry(
        self,
        *,
        subject_fingerprint: bytes,
        current_time: datetime,
    ) -> datetime | None:
        """Return the furthest unexpired block without exposing its subject."""

        # Hold the subject lock for the caller transaction so counting a failure
        # and creating the fifth-failure block cannot race another request.
        self._connection.execute(
            select(
                func.pg_advisory_xact_lock(
                    _credential_lock_key(subject_fingerprint)
                )
            )
        ).scalar_one()

        return self._connection.execute(
            select(func.max(PublicRequestEvent.expires_at)).where(
                PublicRequestEvent.subject_fingerprint == subject_fingerprint,
                PublicRequestEvent.category == PUBLIC_CREDENTIAL_EVENT_CATEGORY,
                PublicRequestEvent.result == PUBLIC_CREDENTIAL_BLOCK_RESULT,
                PublicRequestEvent.expires_at > current_time,
            )
        ).scalar_one()

    def append_event(
        self,
        *,
        subject_fingerprint: bytes,
        result: str,
        occurred_at: datetime,
        expires_at: datetime,
    ) -> None:
        """Persist a bounded operational event with no raw request information."""

        self._connection.execute(
            insert(PublicRequestEvent).values(
                category=PUBLIC_CREDENTIAL_EVENT_CATEGORY,
                result=result,
                subject_fingerprint=subject_fingerprint,
                occurred_at=occurred_at,
                expires_at=expires_at,
            )
        )


def _credential_lock_key(subject_fingerprint: bytes) -> int:
    """Derive a stable signed PostgreSQL advisory key for one subject window."""

    material = subject_fingerprint + b"\x00" + PUBLIC_CREDENTIAL_EVENT_CATEGORY.encode("ascii")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)
