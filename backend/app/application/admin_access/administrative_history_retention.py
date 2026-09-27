"""Purge expired administrative history and identifying associations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.domain.time import normalize_instant


class AdministrativeHistoryRetentionStore(Protocol):
    """Bounded and resumable cleanup operations for administrative retention."""

    def purge_expired_batch(self, *, current_time: datetime) -> int:
        """Delete one bounded batch and report deleted rows across retained data."""

    def next_expiration(self, *, current_time: datetime) -> datetime | None:
        """Return the next future retention deadline, if one exists."""


class PurgeExpiredAdministrativeHistory:
    """Remove only event and identity rows whose calendar-year deadline passed."""

    def __init__(self, *, store: AdministrativeHistoryRetentionStore) -> None:
        self._store = store

    def purge_batch(self, *, current_time: datetime) -> int:
        return self._store.purge_expired_batch(
            current_time=normalize_instant(current_time)
        )

    def next_expiration(self, *, current_time: datetime) -> datetime | None:
        return self._store.next_expiration(
            current_time=normalize_instant(current_time)
        )
