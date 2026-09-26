"""Application boundary for invalidation after administrative security changes."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.domain.time import normalize_instant


class SecurityChangeInvalidationStore(Protocol):
    """Persist all invalidations within the caller-owned transaction."""

    def invalidate_after_security_change(
        self, *, account_id: int, current_time: datetime
    ) -> None:
        """Close sessions and discard incompatible temporary security state."""


class InvalidateAfterSecurityChange:
    """Apply RF-04-CA-06 and RF-04-CA-08 at one controlled instant."""

    def __init__(self, *, store: SecurityChangeInvalidationStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def execute(self, *, account_id: int) -> None:
        """Invalidate account sessions and temporary state after a successful change."""

        self._store.invalidate_after_security_change(
            account_id=_require_account_id(account_id),
            current_time=normalize_instant(self._clock.now()),
        )


def _require_account_id(account_id: int) -> int:
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("administrative account identifier is invalid.")
    return account_id
