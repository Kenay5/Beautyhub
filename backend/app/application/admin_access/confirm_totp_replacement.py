"""Atomically activate an authenticated account's prepared TOTP replacement."""

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
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import Clock
from backend.app.domain.authentication.recovery_code import RecoveryCode
from backend.app.domain.time import normalize_instant
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtectionError
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtectionError
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeError
from backend.app.infrastructure.security.totp import TotpError
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtectionError
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService


@dataclass(frozen=True)
class TotpReplacementConfirmationCandidate:
    account_id: int
    pending_setup_id: int
    pending_ciphertext: bytes = field(repr=False)
    pending_key_version: str
    expires_at: datetime
    verified_totp_factor_id: int | None
    verified_totp_period_counter: int | None
    verified_recovery_code_digest: bytes | None = field(default=None, repr=False)
    active_factor_id: int = 0
    current_email: str = field(default="", repr=False)


@dataclass(frozen=True)
class TotpReplacementConfirmationOutcome:
    status: str
    recovery_codes: tuple[str, ...] = field(default=(), repr=False)
    notification_delivery_id: int | None = None
    notification_recipient: str | None = field(default=None, repr=False)


class LostFactorLinkConsumptionConflict(RuntimeError):
    """Roll back a prepared replacement when its link no longer wins consumption."""


class TotpReplacementConfirmationStore(Protocol):
    def load_candidate(self, *, account_id: int) -> TotpReplacementConfirmationCandidate | None: ...

    def complete_replacement(
        self,
        *,
        candidate: TotpReplacementConfirmationCandidate,
        factor_ciphertext: bytes,
        factor_key_version: str,
        recovery_codes: tuple[RecoveryCode, ...],
        new_period_counter: int,
        current_time: datetime,
        require_original_proof: bool = True,
    ) -> bool: ...

    def discard_pending(
        self, *, candidate: TotpReplacementConfirmationCandidate, status: str, current_time: datetime
    ) -> None: ...


@dataclass(frozen=True)
class ConfirmAdministrativeTotpReplacement:
    store: TotpReplacementConfirmationStore
    credential_guard: EnsureAdministrativeCredentialCheck
    failure_recorder: RecordProtectedAdministrativeCredentialFailure
    pending_factor_protector: object
    factor_protector: object
    totp: object
    recovery_codes: RecoveryCodeService
    invalidator: InvalidateAfterSecurityChange
    audit: RecordAdministrativeAuditEvent
    notifications: RecordSecurityNotificationDelivery
    clock: Clock

    def confirm(self, *, account_id: int, totp_code: str) -> TotpReplacementConfirmationOutcome:
        if not self.credential_guard.ensure_allowed(account_id=account_id):
            self._audit_failure(account_id)
            return TotpReplacementConfirmationOutcome("invalid_credentials")
        candidate = self.store.load_candidate(account_id=account_id)
        if candidate is None:
            self._audit_failure(account_id)
            return TotpReplacementConfirmationOutcome("unavailable")

        now = normalize_instant(self.clock.now())
        if candidate.expires_at <= now:
            self.store.discard_pending(candidate=candidate, status="expired", current_time=now)
            self._audit_failure(account_id)
            return TotpReplacementConfirmationOutcome("unavailable")

        return self._complete_candidate(
            candidate=candidate,
            account_id=account_id,
            totp_code=totp_code,
            current_time=now,
            require_original_proof=True,
        )

    def confirm_lost_factor(
        self,
        *,
        token: bytes,
        link_lifecycle: SecurityLinkLifecycle,
        totp_code: str,
    ) -> TotpReplacementConfirmationOutcome:
        """Complete the email-link flow without creating an authenticated session."""

        located = link_lifecycle.locate(token=token, purpose="totp_replacement")
        if located is None:
            return TotpReplacementConfirmationOutcome("unavailable")

        # Lock the account before its security state or link row (the same order as
        # lost-factor issuance), then revalidate the token and pending setup.
        candidate = self.store.load_candidate(account_id=located.account_id)
        if candidate is None:
            return TotpReplacementConfirmationOutcome("unavailable")
        if not self.credential_guard.ensure_allowed(account_id=located.account_id):
            self._audit_failure(located.account_id)
            return TotpReplacementConfirmationOutcome("unavailable")

        link = link_lifecycle.inspect(token=token, purpose="totp_replacement")
        if link is None or link.link_id != located.link_id:
            return TotpReplacementConfirmationOutcome("unavailable")

        now = normalize_instant(self.clock.now())
        if candidate.expires_at <= now:
            self.store.discard_pending(
                candidate=candidate,
                status="expired",
                current_time=now,
            )
            self._audit_failure(located.account_id)
            return TotpReplacementConfirmationOutcome("unavailable")

        if any(
            value is not None
            for value in (
                candidate.verified_totp_factor_id,
                candidate.verified_totp_period_counter,
                candidate.verified_recovery_code_digest,
            )
        ):
            return TotpReplacementConfirmationOutcome("unavailable")

        return self._complete_candidate(
            candidate=candidate,
            account_id=located.account_id,
            totp_code=totp_code,
            current_time=now,
            require_original_proof=False,
            link_lifecycle=link_lifecycle,
            link_token=token,
        )

    def _complete_candidate(
        self,
        *,
        candidate: TotpReplacementConfirmationCandidate,
        account_id: int,
        totp_code: str,
        current_time: datetime,
        require_original_proof: bool,
        link_lifecycle: SecurityLinkLifecycle | None = None,
        link_token: bytes | None = None,
    ) -> TotpReplacementConfirmationOutcome:
        now = current_time

        if require_original_proof and not self._has_valid_original_proof(candidate):
            self.store.discard_pending(candidate=candidate, status="invalidated", current_time=now)
            self._record_invalid_credentials(account_id)
            return TotpReplacementConfirmationOutcome("invalid_credentials")

        try:
            if candidate.pending_key_version != self.pending_factor_protector.key_version:
                raise PendingTotpProtectionError("pending TOTP key version is invalid.")
            pending_secret = self.pending_factor_protector.decrypt(
                account_id=account_id,
                flow="totp_replacement",
                ciphertext=candidate.pending_ciphertext,
            )
            new_period_counter = self.totp.verify(
                secret=pending_secret,
                code=totp_code,
                now=now,
                used_period_counters=(),
                algorithm="SHA1",
            )
        except (PendingTotpProtectionError, TotpError):
            self.store.discard_pending(candidate=candidate, status="invalidated", current_time=now)
            self._audit_failure(account_id)
            return TotpReplacementConfirmationOutcome("unavailable")
        if new_period_counter is None:
            self.store.discard_pending(candidate=candidate, status="invalidated", current_time=now)
            self._record_invalid_credentials(account_id)
            return TotpReplacementConfirmationOutcome("invalid_credentials")

        try:
            generated = self.recovery_codes.generate()
            stored_codes = tuple(
                RecoveryCode(
                    account_id=account_id,
                    lookup_digest=code.lookup_digest,
                    key_version=self.recovery_codes.key_version,
                    position=position,
                    status="active",
                    used_at=None,
                    invalidated_at=None,
                )
                for position, code in enumerate(generated, start=1)
            )
            factor_ciphertext = self.factor_protector.encrypt(
                account_id=account_id, secret=pending_secret
            )
        except (RecoveryCodeError, RecoveryCodeProtectionError, TotpFactorProtectionError):
            self.store.discard_pending(candidate=candidate, status="invalidated", current_time=now)
            self._audit_failure(account_id)
            return TotpReplacementConfirmationOutcome("unavailable")
        if not self.store.complete_replacement(
            candidate=candidate,
            factor_ciphertext=factor_ciphertext,
            factor_key_version=self.factor_protector.key_version,
            recovery_codes=stored_codes,
            new_period_counter=new_period_counter,
            current_time=now,
            require_original_proof=require_original_proof,
        ):
            self.store.discard_pending(candidate=candidate, status="invalidated", current_time=now)
            self._record_invalid_credentials(account_id)
            return TotpReplacementConfirmationOutcome("invalid_credentials")

        if link_lifecycle is not None:
            assert link_token is not None
            consumed = link_lifecycle.consume(
                token=link_token,
                purpose="totp_replacement",
            )
            if consumed is None or consumed.account_id != account_id:
                raise LostFactorLinkConsumptionConflict(
                    "lost-factor replacement link could not be consumed."
                )

        self.invalidator.execute(account_id=account_id)
        self.audit.record(
            actor_account_id=account_id,
            action="totp_replacement",
            result="succeeded",
        )
        notice = self.notifications.record(
            event="totp_replaced",
            template="totp_replaced_notice",
            recipient=candidate.current_email,
            idempotency_reference=f"totp_replacement:{account_id}:{candidate.pending_setup_id}",
        )
        return TotpReplacementConfirmationOutcome(
            "replaced",
            recovery_codes=tuple(code.display_value for code in generated),
            notification_delivery_id=notice.delivery_id,
            notification_recipient=candidate.current_email,
        )

    def _has_valid_original_proof(self, candidate: TotpReplacementConfirmationCandidate) -> bool:
        has_totp = (
            candidate.verified_totp_factor_id is not None
            and candidate.verified_totp_period_counter is not None
            and candidate.verified_recovery_code_digest is None
        )
        has_recovery = (
            candidate.verified_totp_factor_id is None
            and candidate.verified_totp_period_counter is None
            and candidate.verified_recovery_code_digest is not None
        )
        if has_totp:
            return candidate.verified_totp_factor_id == candidate.active_factor_id
        return has_recovery

    def _record_invalid_credentials(self, account_id: int) -> None:
        self.failure_recorder.record(account_id=account_id, operation="totp_replacement")
        self._audit_failure(account_id)

    def _audit_failure(self, account_id: int) -> None:
        self.audit.record(actor_account_id=account_id, action="totp_replacement", result="failed")
