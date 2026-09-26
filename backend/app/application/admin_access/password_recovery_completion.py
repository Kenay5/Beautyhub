"""Complete a one-use administrative password recovery atomically."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.security_change_invalidation import InvalidateAfterSecurityChange
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.clock import Clock
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.domain.authentication.password_policy import (
    AdministrativePasswordValidationError,
    validate_administrative_password,
)
from backend.app.domain.authentication.security_link import SecurityLinkPurpose


@dataclass(frozen=True)
class RecoveryAccount:
    account_id: int
    purpose: SecurityLinkPurpose
    current_email: str = field(repr=False)


class PasswordRecoveryCompletionStore(Protocol):
    def find_account_for_active_link(self, *, token: bytes) -> tuple[int, SecurityLinkPurpose] | None: ...

    def lock_active_account(self, *, account_id: int, purpose: SecurityLinkPurpose) -> RecoveryAccount | None: ...

    def replace_password(self, *, account_id: int, password_hash: str) -> None: ...

    def restrict_factor_replacement_until_login(self, *, account_id: int) -> None: ...


@dataclass(frozen=True)
class PasswordRecoveryCompletionOutcome:
    status: str
    notification_delivery_id: int | None = None
    notification_recipient: str | None = field(default=None, repr=False)


class CompleteAdministrativePasswordRecovery:
    """Consume, replace credentials, invalidate sessions and audit in one transaction."""

    def __init__(
        self,
        *,
        store: PasswordRecoveryCompletionStore,
        links: SecurityLinkLifecycle,
        password_hasher,
        blocked_passwords,
        invalidator: InvalidateAfterSecurityChange,
        audit: RecordAdministrativeAuditEvent,
        notifications: RecordSecurityNotificationDelivery,
        clock: Clock,
    ) -> None:
        self._store = store
        self._links = links
        self._hasher = password_hasher
        self._blocked = blocked_passwords
        self._invalidator = invalidator
        self._audit = audit
        self._notifications = notifications
        self._clock = clock

    def complete(self, *, token: bytes, new_password: str) -> PasswordRecoveryCompletionOutcome:
        try:
            validate_administrative_password(new_password, blocked_passwords=self._blocked)
        except AdministrativePasswordValidationError:
            return PasswordRecoveryCompletionOutcome(status="invalid_password")

        link_candidate = self._store.find_account_for_active_link(token=token)
        if link_candidate is None:
            return PasswordRecoveryCompletionOutcome(status="invalid_link")
        account_id, purpose = link_candidate
        account = self._store.lock_active_account(account_id=account_id, purpose=purpose)
        if account is None:
            return PasswordRecoveryCompletionOutcome(status="invalid_link")

        consumed = self._links.consume(token=token, purpose=purpose)
        if consumed is None or consumed.account_id != account.account_id:
            return PasswordRecoveryCompletionOutcome(status="invalid_link")

        replacement_hash = self._hasher.hash_password(new_password)
        self._store.replace_password(account_id=account.account_id, password_hash=replacement_hash)
        self._store.restrict_factor_replacement_until_login(account_id=account.account_id)
        self._invalidator.execute(account_id=account.account_id)
        self._audit.record(
            actor_account_id=account.account_id,
            action="password_recovery",
            result="succeeded",
        )
        notice = self._notifications.record(
            event="password_changed",
            template="password_changed_notice",
            recipient=account.current_email,
            idempotency_reference=f"password_recovery:{account.account_id}:{consumed.link_id}",
        )
        return PasswordRecoveryCompletionOutcome(
            status="completed",
            notification_delivery_id=notice.delivery_id,
            notification_recipient=account.current_email,
        )
