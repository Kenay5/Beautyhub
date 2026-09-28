"""Prepare and atomically complete an invited staff member's activation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.pending_security_state import (
    DiscardPendingSecurityState,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import Clock
from backend.app.domain.authentication.pending_security_setup import PendingSecuritySetup
from backend.app.domain.authentication.recovery_code import RecoveryCode
from backend.app.domain.authentication.totp_factor import TotpFactor
from backend.app.domain.time import normalize_instant
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.domain.authentication.password_policy import (
    AdministrativePasswordValidationError,
    BlockedPasswordChecker,
    validate_administrative_password,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHashError,
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

STAFF_ACTIVATION_FLOW = "staff_activation"

class StaffActivationError(ValueError): pass

@dataclass(frozen=True)
class PreparedStaffActivationSetup:
    provisioning_uri: str = field(repr=False)
    manual_key: str = field(repr=False)

@dataclass(frozen=True)
class LockedStaffActivation:
    link_id: int; account_id: int; setup_id: int
    pending_totp_ciphertext: bytes = field(repr=False)
    pending_key_version: str

class StaffActivationSetupStore(Protocol):
    def create_or_get(self, *, setup: PendingSecuritySetup): ...

class StaffActivationStore(Protocol):
    def lock_candidate(self, *, link_id: int, account_id: int, current_time: datetime) -> LockedStaffActivation | None: ...
    def discard_pending(self, *, candidate: LockedStaffActivation, current_time: datetime) -> None: ...
    def activate(self, *, candidate: LockedStaffActivation, password_hash: str, factor: TotpFactor, period_counter: int, recovery_codes: tuple[RecoveryCode, ...], current_time: datetime) -> None: ...

class PrepareStaffActivationSetup:
    def __init__(self, *, link_lifecycle: SecurityLinkLifecycle, setup_store: StaffActivationSetupStore, totp: TotpAuthenticator, protector: PendingTotpProtector, clock: Clock) -> None:
        self._links, self._store, self._totp, self._protector, self._clock = link_lifecycle, setup_store, totp, protector, clock
    def prepare(self, *, token: bytes) -> PreparedStaffActivationSetup:
        link = self._links.inspect(token=token, purpose="invitation")
        if link is None: raise StaffActivationError("staff activation is unavailable.")
        now = normalize_instant(self._clock.now()); secret = self._totp.generate_secret()
        stored = self._store.create_or_get(setup=PendingSecuritySetup(account_id=link.account_id, flow=STAFF_ACTIVATION_FLOW, status="pending", totp_secret_ciphertext=self._protector.encrypt(account_id=link.account_id, flow=STAFF_ACTIVATION_FLOW, secret=secret), key_version=self._protector.key_version, created_at=now, expires_at=link.expires_at))
        value = self._protector.decrypt(account_id=stored.account_id, flow=STAFF_ACTIVATION_FLOW, ciphertext=stored.ciphertext)
        return PreparedStaffActivationSetup(provisioning_uri=self._totp.provisioning_uri(secret=value, account_label="Personal", issuer="Manita de Gato"), manual_key=value.decode("ascii"))


class AbandonStaffActivationSetup:
    """Discard unfinished staff setup without consuming its invitation link."""

    def __init__(
        self,
        *,
        link_lifecycle: SecurityLinkLifecycle,
        pending_state: DiscardPendingSecurityState,
    ) -> None:
        self._link_lifecycle = link_lifecycle
        self._pending_state = pending_state

    def abandon(self, *, token: bytes) -> None:
        link = self._link_lifecycle.inspect(token=token, purpose="invitation")
        if link is None:
            raise StaffActivationError("staff activation is unavailable.")
        self._pending_state.abandoned_setup(
            account_id=link.account_id,
            flow=STAFF_ACTIVATION_FLOW,
        )

@dataclass(frozen=True)
class StaffActivationOutcome:
    recovery_codes: tuple[str, ...] = field(default=(), repr=False)
    rejection: str | None = None
    account_id: int | None = field(default=None, repr=False)
    notification_delivery_id: int | None = field(default=None, repr=False)
    notification_recipient: str | None = field(default=None, repr=False)

class CompleteStaffActivation:
    def __init__(self, *, link_lifecycle: SecurityLinkLifecycle, store: StaffActivationStore, blocked_passwords: BlockedPasswordChecker, password_hasher: AdministrativePasswordHasher, pending_totp_protector: PendingTotpProtector, factor_protector: TotpFactorProtector, totp: TotpAuthenticator, recovery_codes: RecoveryCodeService, audit: RecordAdministrativeAuditEvent, clock: Clock) -> None:
        self._links,self._store,self._blocked,self._hasher,self._pending,self._factor,self._totp,self._codes,self._audit,self._clock=link_lifecycle,store,blocked_passwords,password_hasher,pending_totp_protector,factor_protector,totp,recovery_codes,audit,clock
    def complete(self, *, token: bytes, password: str, totp_code: str) -> StaffActivationOutcome:
        now=normalize_instant(self._clock.now()); link=self._links.inspect(token=token,purpose="invitation")
        if link is None: return StaffActivationOutcome(rejection="unavailable")
        candidate=self._store.lock_candidate(link_id=link.link_id,account_id=link.account_id,current_time=now)
        if candidate is None: return StaffActivationOutcome(rejection="unavailable")
        try: validate_administrative_password(password, blocked_passwords=self._blocked)
        except (AdministrativePasswordValidationError, BlockedPasswordListError):
            self._store.discard_pending(candidate=candidate,current_time=now); return StaffActivationOutcome(rejection="invalid_password")
        try:
            if candidate.pending_key_version != self._pending.key_version:
                raise PendingTotpProtectionError("pending TOTP key version is invalid.")
            secret=self._pending.decrypt(account_id=candidate.account_id,flow=STAFF_ACTIVATION_FLOW,ciphertext=candidate.pending_totp_ciphertext)
            period=self._totp.verify(secret=secret,code=totp_code,now=now)
            if period is None: self._store.discard_pending(candidate=candidate,current_time=now); return StaffActivationOutcome(rejection="unavailable")
            generated=self._codes.generate(); factor=TotpFactor(account_id=candidate.account_id,secret_ciphertext=self._factor.encrypt(account_id=candidate.account_id,secret=secret),key_version=self._factor.key_version,algorithm="SHA1",digits=6,period_seconds=30,status="active",confirmed_at=now,invalidated_at=None)
            records=tuple(RecoveryCode(account_id=candidate.account_id,lookup_digest=item.lookup_digest,key_version=self._codes.key_version,position=i,status="active",used_at=None,invalidated_at=None) for i,item in enumerate(generated,1))
        except (
            AdministrativePasswordHashError,
            PendingTotpProtectionError,
            RecoveryCodeError,
            TotpError,
            TotpFactorProtectionError,
        ):
            self._store.discard_pending(candidate=candidate,current_time=now); return StaffActivationOutcome(rejection="unavailable")
        self._store.activate(candidate=candidate,password_hash=self._hasher.hash_password(password),factor=factor,period_counter=period,recovery_codes=records,current_time=now)
        self._audit.record(actor_account_id=candidate.account_id,action="account_activation",result="succeeded")
        return StaffActivationOutcome(
            recovery_codes=tuple(item.display_value for item in generated),
            account_id=candidate.account_id,
        )
