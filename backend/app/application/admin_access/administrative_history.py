"""Owner-only read use case for minimum administrative audit history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AuthorizationDenialRecorder,
    require_capability,
)
from backend.app.domain.audit.admin_audit_event import (
    AdministrativeAuditAction,
    AdministrativeAuditResult,
)


@dataclass(frozen=True)
class AdministrativeHistoryEntry:
    event_id: int
    actor_account_id: int | None
    action: AdministrativeAuditAction
    result: AdministrativeAuditResult
    occurred_at: datetime
    target_reference: str | None


@dataclass(frozen=True)
class AdministrativeHistoryFilters:
    account_id: int | None = None
    action: AdministrativeAuditAction | None = None
    start_inclusive: datetime | None = None
    end_exclusive: datetime | None = None

    def __post_init__(self) -> None:
        if self.account_id is not None and (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise ValueError("administrative history account filter is invalid")
        for boundary in (self.start_inclusive, self.end_exclusive):
            if boundary is not None and (
                boundary.tzinfo is None or boundary.utcoffset() is None
            ):
                raise ValueError("administrative history boundary must be aware")
        if (
            self.start_inclusive is not None
            and self.end_exclusive is not None
            and self.start_inclusive >= self.end_exclusive
        ):
            raise ValueError("administrative history period is invalid")


class AdministrativeHistoryStore(Protocol):
    def list_events(
        self, *, filters: AdministrativeHistoryFilters, current_time: datetime
    ) -> tuple[AdministrativeHistoryEntry, ...]: ...

    def list_actor_account_ids(self, *, current_time: datetime) -> tuple[int, ...]: ...

    def get_event(
        self, *, event_id: int, current_time: datetime
    ) -> AdministrativeHistoryEntry | None: ...


class QueryAdministrativeHistory:
    """Authorize from the authenticated actor, then read unexpired event data."""

    def __init__(
        self,
        *,
        store: AdministrativeHistoryStore,
        clock,
        denial_recorder: AuthorizationDenialRecorder,
    ) -> None:
        self._store = store
        self._clock = clock
        self._denial_recorder = denial_recorder

    def list_events(
        self,
        *,
        actor: AdministrativeActor,
        filters: AdministrativeHistoryFilters,
    ) -> tuple[tuple[AdministrativeHistoryEntry, ...], tuple[int, ...]]:
        self._require_history_access(actor=actor)
        current_time = self._clock.now()
        return (
            self._store.list_events(filters=filters, current_time=current_time),
            self._store.list_actor_account_ids(current_time=current_time),
        )

    def get_event(
        self, *, actor: AdministrativeActor, event_id: int
    ) -> AdministrativeHistoryEntry | None:
        self._require_history_access(actor=actor)
        return self._store.get_event(
            event_id=event_id, current_time=self._clock.now()
        )

    def _require_history_access(self, *, actor: AdministrativeActor) -> None:
        require_capability(
            actor=actor,
            capability="view_administrative_history",
            audit=self._denial_recorder,
        )
