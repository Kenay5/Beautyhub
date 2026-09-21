"""Idempotent administrative logout without retaining opaque session values."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.domain.time import normalize_instant


class AdministrativeSessionLogoutStore(Protocol):
    def invalidate_active_session(
        self, *, session_digest: bytes, current_time: datetime
    ) -> int | None: ...


class AdministrativeSessionTokenProtector(Protocol):
    def digest_session_token(self, token: bytes) -> bytes: ...


class AdministrativeLogoutAuditRecorder(Protocol):
    def record(
        self,
        *,
        actor_account_id: int | None,
        action: str,
        result: str,
        target_reference: str | None = None,
    ) -> None: ...


class CloseAdministrativeSession:
    """Invalidate one active session once and audit only its first transition."""

    def __init__(
        self,
        *,
        store: AdministrativeSessionLogoutStore,
        protector: AdministrativeSessionTokenProtector,
        audit: AdministrativeLogoutAuditRecorder,
        clock: Clock,
    ) -> None:
        self._store = store
        self._protector = protector
        self._audit = audit
        self._clock = clock

    def close(self, *, session_token: bytes) -> bool:
        account_id = self._store.invalidate_active_session(
            session_digest=self._protector.digest_session_token(session_token),
            current_time=normalize_instant(self._clock.now()),
        )
        if account_id is None:
            return False
        self._audit.record(
            actor_account_id=account_id,
            action="logout",
            result="succeeded",
        )
        return True
