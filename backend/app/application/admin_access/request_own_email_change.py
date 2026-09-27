"""Reserve an authenticated administrator's own replacement email."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.clock import Clock
from backend.app.domain.authentication.admin_email_claim import (
    AdministrativeEmailClaimError,
)
from backend.app.domain.time import normalize_instant


@dataclass(frozen=True)
class OwnEmailChangeCandidate:
    account_id: int
    password_hash: str = field(repr=False)
    factor_id: int
    factor_ciphertext: bytes = field(repr=False)
    factor_key_version: str
    factor_algorithm: str
    used_period_counters: tuple[int, ...]


class OwnEmailChangeStore(Protocol):
    def load_candidate(self, *, account_id: int) -> OwnEmailChangeCandidate | None: ...

    def reserve_email(
        self,
        *,
        candidate: OwnEmailChangeCandidate,
        email,
        period_counter: int,
        current_time: datetime,
    ) -> bool: ...


class RequestOwnAdministrativeEmailChange:
    """Validate credentials and reserve a protected address without changing it."""

    def __init__(
        self,
        *,
        store: OwnEmailChangeStore,
        email_protector,
        credential_guard: EnsureAdministrativeCredentialCheck,
        failure_recorder: RecordProtectedAdministrativeCredentialFailure,
        password_hasher,
        factor_protector,
        totp,
        audit: RecordAdministrativeAuditEvent,
        clock: Clock,
    ) -> None:
        self._store = store
        self._email_protector = email_protector
        self._guard = credential_guard
        self._failures = failure_recorder
        self._password_hasher = password_hasher
        self._factor_protector = factor_protector
        self._totp = totp
        self._audit = audit
        self._clock = clock

    def request(
        self,
        *,
        account_id: int,
        new_email: str,
        current_password: str,
        totp_code: str,
    ) -> str:
        try:
            protected_email = self._email_protector.protect(new_email)
        except (AdministrativeEmailClaimError, ValueError):
            self._record_audit(account_id, "failed")
            return "invalid_email"

        if not self._guard.ensure_allowed(account_id=account_id):
            self._record_audit(account_id, "failed")
            return "invalid_credentials"

        candidate = self._store.load_candidate(account_id=account_id)
        if candidate is None:
            self._record_audit(account_id, "failed")
            return "unavailable"

        now = normalize_instant(self._clock.now())
        password = self._password_hasher.verify_and_upgrade(
            stored_hash=candidate.password_hash,
            password=current_password,
        )
        period_counter: int | None = None
        if candidate.factor_key_version == self._factor_protector.key_version:
            secret = self._factor_protector.decrypt(
                account_id=account_id,
                ciphertext=candidate.factor_ciphertext,
            )
            period_counter = self._totp.verify(
                secret=secret,
                code=totp_code,
                now=now,
                used_period_counters=candidate.used_period_counters,
                algorithm=candidate.factor_algorithm,
            )
        if not password.verified or period_counter is None:
            self._failures.record(account_id=account_id, operation="email_change")
            self._record_audit(account_id, "failed")
            return "invalid_credentials"

        if not self._store.reserve_email(
            candidate=candidate,
            email=protected_email,
            period_counter=period_counter,
            current_time=now,
        ):
            self._record_audit(account_id, "failed")
            return "unavailable"

        # The email is only reserved here; the audited change occurs after
        # successful confirmation of the one-use link.
        return "reserved"

    def _record_audit(self, account_id: int, result: str) -> None:
        self._audit.record(
            actor_account_id=account_id,
            action="email_change",
            result=result,
        )
