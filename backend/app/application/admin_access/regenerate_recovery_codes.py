"""Regenerate recovery credentials for an authenticated administrative account."""

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
from backend.app.domain.authentication.recovery_code import RecoveryCode
from backend.app.domain.time import normalize_instant
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService


@dataclass(frozen=True)
class RecoveryCodeRegenerationCandidate:
    account_id: int
    password_hash: str = field(repr=False)
    factor_id: int
    factor_ciphertext: bytes = field(repr=False)
    factor_key_version: str
    factor_algorithm: str
    used_period_counters: tuple[int, ...]
    current_email: str = field(repr=False)


@dataclass(frozen=True)
class RecoveryCodeRegenerationOutcome:
    status: str
    recovery_codes: tuple[str, ...] = field(default=(), repr=False)
    notification_delivery_id: int | None = None
    notification_recipient: str | None = field(default=None, repr=False)


class RecoveryCodeRegenerationStore(Protocol):
    def load_candidate(
        self, *, account_id: int
    ) -> RecoveryCodeRegenerationCandidate | None: ...

    def replace_codes(
        self,
        *,
        candidate: RecoveryCodeRegenerationCandidate,
        recovery_codes: tuple[RecoveryCode, ...],
        period_counter: int,
        current_time: datetime,
    ) -> bool: ...


class RegenerateAdministrativeRecoveryCodes:
    """Replace the complete code batch only after both credentials succeed."""

    def __init__(
        self,
        *,
        store: RecoveryCodeRegenerationStore,
        credential_guard: EnsureAdministrativeCredentialCheck,
        failure_recorder: RecordProtectedAdministrativeCredentialFailure,
        password_hasher,
        factor_protector,
        totp,
        recovery_codes: RecoveryCodeService,
        invalidator: InvalidateAfterSecurityChange,
        audit: RecordAdministrativeAuditEvent,
        notifications: RecordSecurityNotificationDelivery,
        clock: Clock,
    ) -> None:
        self._store = store
        self._guard = credential_guard
        self._failures = failure_recorder
        self._password_hasher = password_hasher
        self._factor_protector = factor_protector
        self._totp = totp
        self._recovery_codes = recovery_codes
        self._invalidator = invalidator
        self._audit = audit
        self._notifications = notifications
        self._clock = clock

    def regenerate(
        self, *, account_id: int, current_password: str, totp_code: str
    ) -> RecoveryCodeRegenerationOutcome:
        """Perform the transition inside the caller-owned PostgreSQL transaction."""

        if not self._guard.ensure_allowed(account_id=account_id):
            self._record_failure_audit(account_id)
            return RecoveryCodeRegenerationOutcome(status="invalid_credentials")

        candidate = self._store.load_candidate(account_id=account_id)
        if candidate is None:
            self._record_failure_audit(account_id)
            return RecoveryCodeRegenerationOutcome(status="unavailable")

        now = normalize_instant(self._clock.now())
        password = self._password_hasher.verify_and_upgrade(
            stored_hash=candidate.password_hash,
            password=current_password,
        )
        period_counter: int | None = None
        if candidate.factor_key_version == self._factor_protector.key_version:
            factor_secret = self._factor_protector.decrypt(
                account_id=account_id,
                ciphertext=candidate.factor_ciphertext,
            )
            period_counter = self._totp.verify(
                secret=factor_secret,
                code=totp_code,
                now=now,
                used_period_counters=candidate.used_period_counters,
                algorithm=candidate.factor_algorithm,
            )

        if not password.verified or period_counter is None:
            self._record_invalid_credentials(account_id)
            return RecoveryCodeRegenerationOutcome(status="invalid_credentials")

        generated_codes = self._recovery_codes.generate()
        stored_codes = tuple(
            RecoveryCode(
                account_id=account_id,
                lookup_digest=generated.lookup_digest,
                key_version=self._recovery_codes.key_version,
                position=position,
                status="active",
                used_at=None,
                invalidated_at=None,
            )
            for position, generated in enumerate(generated_codes, start=1)
        )
        if not self._store.replace_codes(
            candidate=candidate,
            recovery_codes=stored_codes,
            period_counter=period_counter,
            current_time=now,
        ):
            self._record_invalid_credentials(account_id)
            return RecoveryCodeRegenerationOutcome(status="invalid_credentials")

        self._invalidator.execute(account_id=account_id)
        self._audit.record(
            actor_account_id=account_id,
            action="recovery_code_regeneration",
            result="succeeded",
        )
        notice = self._notifications.record(
            event="recovery_codes_changed",
            template="recovery_codes_changed_notice",
            recipient=candidate.current_email,
            idempotency_reference=(
                f"recovery_codes:{account_id}:{candidate.factor_id}:{period_counter}"
            ),
        )
        return RecoveryCodeRegenerationOutcome(
            status="regenerated",
            recovery_codes=tuple(code.display_value for code in generated_codes),
            notification_delivery_id=notice.delivery_id,
            notification_recipient=candidate.current_email,
        )

    def _record_invalid_credentials(self, account_id: int) -> None:
        self._failures.record(
            account_id=account_id,
            operation="recovery_code_regeneration",
        )
        self._record_failure_audit(account_id)

    def _record_failure_audit(self, account_id: int) -> None:
        self._audit.record(
            actor_account_id=account_id,
            action="recovery_code_regeneration",
            result="failed",
        )
