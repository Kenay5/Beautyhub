"""Application boundary for writing minimum administrative audit evidence."""

from __future__ import annotations

from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.domain.audit.admin_audit_event import (
    AdministrativeAuditAction,
    AdministrativeAuditEvent,
    AdministrativeAuditResult,
)
from backend.app.domain.time import normalize_instant


class AdministrativeAuditStore(Protocol):
    """Append minimum audit evidence without accepting copied private data."""

    def append(self, *, event: AdministrativeAuditEvent) -> None:
        """Persist an already-validated administrative event."""


class RecordAdministrativeAuditEvent:
    """Write one controlled administrative event at the supplied clock instant."""

    def __init__(self, *, store: AdministrativeAuditStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def record(
        self,
        *,
        actor_account_id: int | None,
        action: AdministrativeAuditAction,
        result: AdministrativeAuditResult,
        target_reference: str | None = None,
    ) -> None:
        """Create only the minimum approved event fields."""

        self._store.append(
            event=AdministrativeAuditEvent(
                actor_account_id=actor_account_id,
                action=action,
                result=result,
                occurred_at=normalize_instant(self._clock.now()),
                target_reference=target_reference,
            )
        )
