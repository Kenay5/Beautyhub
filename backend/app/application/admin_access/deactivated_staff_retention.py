"""Purge expired identifying associations for deactivated staff accounts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.domain.time import normalize_instant


class DeactivatedStaffRetentionStore(Protocol):
    """Internal bounded cleanup operations for retained staff identities."""

    def purge_expired_identity_batch(self, *, current_time: datetime) -> int:
        """Delete at most one batch whose identifying retention has expired."""

    def next_identity_expiration(self, *, current_time: datetime) -> datetime | None:
        """Return the next future identifying-retention deadline, if any."""


class PurgeExpiredDeactivatedStaffIdentities:
    """Remove only expired encrypted identity archives, never history references."""

    def __init__(self, *, store: DeactivatedStaffRetentionStore) -> None:
        self._store = store

    def purge_batch(self, *, current_time: datetime) -> int:
        return self._store.purge_expired_identity_batch(
            current_time=normalize_instant(current_time)
        )

    def next_expiration(self, *, current_time: datetime) -> datetime | None:
        return self._store.next_identity_expiration(
            current_time=normalize_instant(current_time)
        )
