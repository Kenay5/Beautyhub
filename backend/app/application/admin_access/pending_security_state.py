"""Application boundary for discarding incomplete administrative security state."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.domain.authentication.pending_security_setup import (
    PendingSecuritySetupFlow,
)
from backend.app.domain.authentication.security_link import SecurityLinkPurpose
from backend.app.domain.time import normalize_instant


class PendingSecurityStateStore(Protocol):
    """Persist cleanup of temporary security artifacts within the caller transaction."""

    def discard_for_expired_link(
        self, *, account_id: int, purpose: SecurityLinkPurpose, current_time: datetime
    ) -> None:
        """Discard artifacts that cannot survive one expired link."""

    def discard_abandoned_setup(
        self, *, account_id: int, flow: PendingSecuritySetupFlow, current_time: datetime
    ) -> None:
        """Discard one setup abandoned before it became an active factor."""

    def discard_for_replaced_link(
        self, *, account_id: int, purpose: SecurityLinkPurpose, current_time: datetime
    ) -> None:
        """Discard artifacts made obsolete by one replacement link."""

    def discard_after_completed_security_change(
        self, *, account_id: int, current_time: datetime
    ) -> None:
        """Apply the approved general invalidation without touching active credentials."""


class DiscardPendingSecurityState:
    """Apply T029 cleanup at controlled clock instants."""

    def __init__(self, *, store: PendingSecurityStateStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def expired_link(self, *, account_id: int, purpose: SecurityLinkPurpose) -> None:
        """Discard only artifacts made unusable when one link expires."""

        self._store.discard_for_expired_link(
            account_id=_require_account_id(account_id),
            purpose=purpose,
            current_time=normalize_instant(self._clock.now()),
        )

    def abandoned_setup(
        self, *, account_id: int, flow: PendingSecuritySetupFlow
    ) -> None:
        """Discard one incomplete setup while preserving its existing credentials."""

        self._store.discard_abandoned_setup(
            account_id=_require_account_id(account_id),
            flow=flow,
            current_time=normalize_instant(self._clock.now()),
        )

    def replaced_link(self, *, account_id: int, purpose: SecurityLinkPurpose) -> None:
        """Discard only artifacts tied to a replaced pending link."""

        self._store.discard_for_replaced_link(
            account_id=_require_account_id(account_id),
            purpose=purpose,
            current_time=normalize_instant(self._clock.now()),
        )

    def completed_security_change(self, *, account_id: int) -> None:
        """Invalidate all previously pending security artifacts for one account."""

        self._store.discard_after_completed_security_change(
            account_id=_require_account_id(account_id),
            current_time=normalize_instant(self._clock.now()),
        )


def _require_account_id(account_id: int) -> int:
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("administrative account identifier is invalid.")
    return account_id
