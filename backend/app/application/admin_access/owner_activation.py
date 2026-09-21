"""Atomically complete the initial owner activation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import Clock
from backend.app.domain.authentication.password_policy import (
    AdministrativePasswordValidationError,
    BlockedPasswordChecker,
    validate_administrative_password,
)
from backend.app.domain.authentication.recovery_code import RecoveryCode
from backend.app.domain.authentication.totp_factor import TotpFactor
from backend.app.domain.time import normalize_instant
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHashError,
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.blocked_passwords import BlockedPasswordListError
from backend.app.infrastructure.security.pending_totp_protection import (
    PendingTotpProtectionError,
    PendingTotpProtector,
)
from backend.app.infrastructure.security.recovery_codes import (
    RecoveryCodeError,
    RecoveryCodeService,
)
from backend.app.infrastructure.security.totp import TotpAuthenticator, TotpError
from backend.app.infrastructure.security.totp_factor_protection import (
    TotpFactorProtectionError,
    TotpFactorProtector,
)


OwnerActivationRejection = Literal["unavailable", "invalid_password"]


@dataclass(frozen=True)
class LockedOwnerActivation:
    """Locked identifiers and encrypted setup state for one activation attempt."""

    link_id: int
    account_id: int
    setup_id: int
    pending_totp_ciphertext: bytes = field(repr=False)
    pending_key_version: str


@dataclass(frozen=True)
class OwnerActivationOutcome:
    """Either ten one-time codes or one sanitized rejection category."""

    recovery_codes: tuple[str, ...] = field(default=(), repr=False)
    rejection: OwnerActivationRejection | None = None

    @property
    def activated(self) -> bool:
        return self.rejection is None


class OwnerActivationStore(Protocol):
    """Persist the complete owner transition in the caller transaction."""

    def lock_candidate(
        self,
        *,
        link_id: int,
        account_id: int,
        current_time: datetime,
    ) -> LockedOwnerActivation | None:
        """Lock and revalidate every row governing initial activation."""

    def discard_pending(
        self, *, candidate: LockedOwnerActivation, current_time: datetime
    ) -> None:
        """Erase the rejected unconfirmed TOTP material."""

    def activate(
        self,
        *,
        candidate: LockedOwnerActivation,
        password_hash: str,
        factor: TotpFactor,
        period_counter: int,
        recovery_codes: tuple[RecoveryCode, ...],
        current_time: datetime,
    ) -> None:
        """Commit credentials, factor, codes, link, account and bootstrap together."""


class CompleteOwnerActivation:
    """Validate the pending factors and complete one owner activation without a session."""

    def __init__(
        self,
        *,
        link_lifecycle: SecurityLinkLifecycle,
        store: OwnerActivationStore,
        blocked_passwords: BlockedPasswordChecker,
        password_hasher: AdministrativePasswordHasher,
        pending_totp_protector: PendingTotpProtector,
        factor_protector: TotpFactorProtector,
        totp: TotpAuthenticator,
        recovery_codes: RecoveryCodeService,
        audit: RecordAdministrativeAuditEvent,
        clock: Clock,
    ) -> None:
        self._link_lifecycle = link_lifecycle
        self._store = store
        self._blocked_passwords = blocked_passwords
        self._password_hasher = password_hasher
        self._pending_totp_protector = pending_totp_protector
        self._factor_protector = factor_protector
        self._totp = totp
        self._recovery_codes = recovery_codes
        self._audit = audit
        self._clock = clock

    def complete(
        self,
        *,
        token: bytes,
        password: str,
        totp_code: str,
    ) -> OwnerActivationOutcome:
        """Return one-time recovery codes only after every activation write succeeds."""

        current_time = normalize_instant(self._clock.now())
        link = self._link_lifecycle.inspect(token=token, purpose="initial_activation")
        if link is None:
            return OwnerActivationOutcome(rejection="unavailable")

        candidate = self._store.lock_candidate(
            link_id=link.link_id,
            account_id=link.account_id,
            current_time=current_time,
        )
        if candidate is None:
            return OwnerActivationOutcome(rejection="unavailable")

        try:
            validate_administrative_password(
                password,
                blocked_passwords=self._blocked_passwords,
            )
        except (AdministrativePasswordValidationError, BlockedPasswordListError):
            self._store.discard_pending(
                candidate=candidate,
                current_time=current_time,
            )
            return OwnerActivationOutcome(rejection="invalid_password")

        try:
            if candidate.pending_key_version != self._pending_totp_protector.key_version:
                raise PendingTotpProtectionError("pending TOTP key version is invalid.")
            secret = self._pending_totp_protector.decrypt(
                account_id=candidate.account_id,
                flow="owner_activation",
                ciphertext=candidate.pending_totp_ciphertext,
            )
            period_counter = self._totp.verify(
                secret=secret,
                code=totp_code,
                now=current_time,
            )
            if period_counter is None:
                self._store.discard_pending(
                    candidate=candidate,
                    current_time=current_time,
                )
                return OwnerActivationOutcome(rejection="unavailable")

            password_hash = self._password_hasher.hash_password(password)
            factor = TotpFactor(
                account_id=candidate.account_id,
                secret_ciphertext=self._factor_protector.encrypt(
                    account_id=candidate.account_id,
                    secret=secret,
                ),
                key_version=self._factor_protector.key_version,
                algorithm="SHA1",
                digits=6,
                period_seconds=30,
                status="active",
                confirmed_at=current_time,
                invalidated_at=None,
            )
            generated_codes = self._recovery_codes.generate()
            recovery_records = tuple(
                RecoveryCode(
                    account_id=candidate.account_id,
                    lookup_digest=generated.lookup_digest,
                    key_version=self._recovery_codes.key_version,
                    position=position,
                    status="active",
                    used_at=None,
                    invalidated_at=None,
                )
                for position, generated in enumerate(generated_codes, start=1)
            )
        except (
            AdministrativePasswordHashError,
            PendingTotpProtectionError,
            RecoveryCodeError,
            TotpError,
            TotpFactorProtectionError,
        ):
            self._store.discard_pending(
                candidate=candidate,
                current_time=current_time,
            )
            return OwnerActivationOutcome(rejection="unavailable")

        self._store.activate(
            candidate=candidate,
            password_hash=password_hash,
            factor=factor,
            period_counter=period_counter,
            recovery_codes=recovery_records,
            current_time=current_time,
        )
        self._audit.record(
            actor_account_id=candidate.account_id,
            action="account_activation",
            result="succeeded",
        )
        return OwnerActivationOutcome(
            recovery_codes=tuple(code.display_value for code in generated_codes)
        )
