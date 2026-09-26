"""Change an authenticated administrative account's password atomically."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.security_change_invalidation import (
    InvalidateAfterSecurityChange,
)
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import Clock
from backend.app.domain.authentication.password_policy import (
    AdministrativePasswordValidationError,
    validate_administrative_password,
)
from backend.app.domain.time import normalize_instant


@dataclass(frozen=True)
class PasswordChangeCandidate:
    account_id: int
    password_hash: str = field(repr=False)
    factor_id: int
    factor_ciphertext: bytes = field(repr=False)
    factor_key_version: str
    factor_algorithm: str
    used_period_counters: tuple[int, ...]
    current_email: str = field(repr=False)


@dataclass(frozen=True)
class PasswordChangeOutcome:
    status: str
    notification_delivery_id: int | None = None
    notification_recipient: str | None = field(default=None, repr=False)


class PasswordChangeStore(Protocol):
    def load_candidate(self, *, account_id: int) -> PasswordChangeCandidate | None: ...

    def replace_password(
        self,
        *,
        candidate: PasswordChangeCandidate,
        password_hash: str,
        period_counter: int,
        current_time: datetime,
    ) -> bool: ...


class ChangeAdministrativePassword:
    """Keep credential consumption, replacement and side effects in one transaction."""

    def __init__(
        self,
        *,
        store: PasswordChangeStore,
        credential_guard: EnsureAdministrativeCredentialCheck,
        failure_recorder: RecordProtectedAdministrativeCredentialFailure,
        password_hasher,
        factor_protector,
        totp,
        blocked_passwords,
        invalidator: InvalidateAfterSecurityChange,
        audit: RecordAdministrativeAuditEvent,
        notifications: RecordSecurityNotificationDelivery,
        clock: Clock,
    ) -> None:
        self._store = store
        self._guard = credential_guard
        self._failures = failure_recorder
        self._hasher = password_hasher
        self._factor = factor_protector
        self._totp = totp
        self._blocked = blocked_passwords
        self._invalidator = invalidator
        self._audit = audit
        self._notifications = notifications
        self._clock = clock

    def change(
        self,
        *,
        account_id: int,
        current_password: str,
        totp_code: str,
        new_password: str,
    ) -> PasswordChangeOutcome:
        """Return a sanitized result; the caller owns the database transaction."""

        if not self._guard.ensure_allowed(account_id=account_id):
            self._record_failure_audit(account_id)
            return PasswordChangeOutcome(status="invalid_credentials")
        candidate = self._store.load_candidate(account_id=account_id)
        if candidate is None:
            self._record_failure_audit(account_id)
            return PasswordChangeOutcome(status="unavailable")

        now = normalize_instant(self._clock.now())
        verification = self._hasher.verify_and_upgrade(
            stored_hash=candidate.password_hash,
            password=current_password,
        )
        period: int | None = None
        if candidate.factor_key_version == self._factor.key_version:
            secret = self._factor.decrypt(
                account_id=account_id,
                ciphertext=candidate.factor_ciphertext,
            )
            period = self._totp.verify(
                secret=secret,
                code=totp_code,
                now=now,
                used_period_counters=candidate.used_period_counters,
                algorithm=candidate.factor_algorithm,
            )
        if not verification.verified or period is None:
            self._record_invalid_credentials(account_id)
            return PasswordChangeOutcome(status="invalid_credentials")

        try:
            validate_administrative_password(
                new_password, blocked_passwords=self._blocked
            )
        except AdministrativePasswordValidationError:
            self._record_failure_audit(account_id)
            return PasswordChangeOutcome(status="invalid_password")
        except ValueError:
            self._record_failure_audit(account_id)
            return PasswordChangeOutcome(status="unavailable")

        replacement_hash = self._hasher.hash_password(new_password)
        if not self._store.replace_password(
            candidate=candidate,
            password_hash=replacement_hash,
            period_counter=period,
            current_time=now,
        ):
            self._record_invalid_credentials(account_id)
            return PasswordChangeOutcome(status="invalid_credentials")

        self._invalidator.execute(account_id=account_id)
        self._audit.record(
            actor_account_id=account_id,
            action="password_change",
            result="succeeded",
        )
        notice = self._notifications.record(
            event="password_changed",
            template="password_changed_notice",
            recipient=candidate.current_email,
            idempotency_reference=(
                f"password_change:{account_id}:{candidate.factor_id}:{period}"
            ),
        )
        return PasswordChangeOutcome(
            status="changed",
            notification_delivery_id=notice.delivery_id,
            notification_recipient=candidate.current_email,
        )

    def _record_invalid_credentials(self, account_id: int) -> None:
        self._failures.record(account_id=account_id, operation="password_change")
        self._record_failure_audit(account_id)

    def _record_failure_audit(self, account_id: int) -> None:
        self._audit.record(
            actor_account_id=account_id,
            action="password_change",
            result="failed",
        )
