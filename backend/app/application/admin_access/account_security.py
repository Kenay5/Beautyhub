"""Application boundary for administrative credential-failure persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.domain.authentication.account_security import (
    AdministrativeCredentialFailureResult,
    AdministrativeCredentialOperation,
)
from backend.app.domain.time import normalize_instant


class AdministrativeAccountSecurityStore(Protocol):
    """Persist account security state without accepting credential values."""

    def record_rejected_credential_request(
        self,
        *,
        account_id: int,
        operation: AdministrativeCredentialOperation,
        current_time: datetime,
    ) -> AdministrativeCredentialFailureResult:
        """Record at most one event for this already-rejected request."""

    def set_post_recovery_second_factor_restriction(
        self, *, account_id: int
    ) -> None:
        """Require a later full authentication before lost-factor replacement."""

    def ensure_credential_check_allowed(
        self, *, account_id: int, current_time: datetime
    ) -> bool:
        """Reject a current lock without recording another credential failure."""


class AdministrativeLockAuditRecorder(Protocol):
    def record(
        self,
        *,
        actor_account_id: int | None,
        action: str,
        result: str,
        target_reference: str | None = None,
    ) -> None: ...


class AdministrativeLockNotificationRecorder(Protocol):
    def record(
        self,
        *,
        event: str,
        template: str,
        recipient: str,
        idempotency_reference: str | None = None,
    ): ...


class AdministrativeLockRecipientDirectory(Protocol):
    def lock_notification_recipients(self, *, account_id: int) -> tuple[str, ...]: ...


class RecordAdministrativeCredentialFailure:
    """Record one rejected request using the approved, controlled clock."""

    def __init__(
        self, *, store: AdministrativeAccountSecurityStore, clock: Clock
    ) -> None:
        self._store = store
        self._clock = clock

    def record(
        self,
        *,
        account_id: int,
        operation: AdministrativeCredentialOperation,
    ) -> AdministrativeCredentialFailureResult:
        """Delegate the row-locked state transition to persistence."""

        _require_account_id(account_id)
        return self._store.record_rejected_credential_request(
            account_id=account_id,
            operation=operation,
            current_time=normalize_instant(self._clock.now()),
        )


class EnsureAdministrativeCredentialCheck:
    """Guard login and sensitive credential checks before their verification work."""

    def __init__(
        self, *, store: AdministrativeAccountSecurityStore, clock: Clock
    ) -> None:
        self._store = store
        self._clock = clock

    def ensure_allowed(self, *, account_id: int) -> bool:
        _require_account_id(account_id)
        return self._store.ensure_credential_check_allowed(
            account_id=account_id,
            current_time=normalize_instant(self._clock.now()),
        )


class RecordProtectedAdministrativeCredentialFailure:
    """Record a failure and prepare the effects of a newly-created account lock."""

    def __init__(
        self,
        *,
        failure_recorder: RecordAdministrativeCredentialFailure,
        audit: AdministrativeLockAuditRecorder,
        notifications: AdministrativeLockNotificationRecorder,
        recipients: AdministrativeLockRecipientDirectory,
    ) -> None:
        self._failure_recorder = failure_recorder
        self._audit = audit
        self._notifications = notifications
        self._recipients = recipients

    def record(
        self,
        *,
        account_id: int,
        operation: AdministrativeCredentialOperation,
    ) -> AdministrativeCredentialFailureResult:
        outcome = self._failure_recorder.record(
            account_id=account_id,
            operation=operation,
        )
        if not outcome.started_lock:
            return outcome

        self._audit.record(
            actor_account_id=account_id,
            action="account_locked",
            result="succeeded",
            target_reference=f"admin_account:{account_id}",
        )
        idempotency_reference = f"credential_failure:{outcome.failure_event_id}"
        for recipient in self._recipients.lock_notification_recipients(
            account_id=account_id
        ):
            self._notifications.record(
                event="account_locked",
                template="account_locked_notice",
                recipient=recipient,
                idempotency_reference=idempotency_reference,
            )
        return outcome


class RestrictPostRecoveryFactorReplacement:
    """Persist the approved restriction left by a password-recovery flow."""

    def __init__(self, *, store: AdministrativeAccountSecurityStore) -> None:
        self._store = store

    def apply(self, *, account_id: int) -> None:
        """Set the restriction without accepting a password or factor value."""

        _require_account_id(account_id)
        self._store.set_post_recovery_second_factor_restriction(account_id=account_id)


def _require_account_id(account_id: int) -> None:
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("administrative account identifier is invalid.")
