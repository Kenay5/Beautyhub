"""Prepare, but do not activate, an authenticated TOTP-factor replacement."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.clock import Clock
from backend.app.domain.authentication.pending_security_setup import PendingSecuritySetup
from backend.app.domain.time import normalize_instant


TOTP_REPLACEMENT_FLOW = "totp_replacement"
TOTP_REPLACEMENT_TTL = timedelta(minutes=30)
TOTP_REPLACEMENT_ISSUER = "Manita de Gato"


@dataclass(frozen=True)
class TotpReplacementCandidate:
    account_id: int
    password_hash: str = field(repr=False)
    factor_id: int
    factor_ciphertext: bytes = field(repr=False)
    factor_key_version: str
    factor_algorithm: str
    used_period_counters: tuple[int, ...]
    active_recovery_digests: tuple[bytes, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class PreparedTotpReplacement:
    provisioning_uri: str = field(repr=False)
    manual_key: str = field(repr=False)


class TotpReplacementStore(Protocol):
    def load_candidate(self, *, account_id: int) -> TotpReplacementCandidate | None: ...

    def save_pending_setup(
        self, *, setup: PendingSecuritySetup,
        verified_totp_factor_id: int | None,
        verified_totp_period_counter: int | None,
        verified_recovery_code_digest: bytes | None,
    ) -> bool: ...


class CredentialFailureRecorder(Protocol):
    def record(self, *, account_id: int, operation: str): ...


class PrepareAdministrativeTotpReplacement:
    """Persist a new encrypted factor and its unconsumed proof reference."""

    def __init__(
        self,
        *,
        store: TotpReplacementStore,
        credential_guard: EnsureAdministrativeCredentialCheck,
        failure_recorder: CredentialFailureRecorder,
        password_hasher,
        factor_protector,
        pending_factor_protector,
        totp,
        recovery_codes,
        audit: RecordAdministrativeAuditEvent,
        clock: Clock,
    ) -> None:
        self._store = store
        self._guard = credential_guard
        self._failures = failure_recorder
        self._password_hasher = password_hasher
        self._factor_protector = factor_protector
        self._pending_factor_protector = pending_factor_protector
        self._totp = totp
        self._recovery_codes = recovery_codes
        self._audit = audit
        self._clock = clock

    def prepare(
        self,
        *,
        account_id: int,
        current_password: str,
        totp_code: str | None = None,
        recovery_code: str | None = None,
    ) -> PreparedTotpReplacement | str:
        if not self._guard.ensure_allowed(account_id=account_id):
            self._record_failed_audit(account_id)
            return "invalid_credentials"

        candidate = self._store.load_candidate(account_id=account_id)
        if candidate is None:
            self._record_failed_audit(account_id)
            return "unavailable"

        now = normalize_instant(self._clock.now())
        password = self._password_hasher.verify_and_upgrade(
            stored_hash=candidate.password_hash,
            password=current_password,
        )
        factor_count = sum(value is not None for value in (totp_code, recovery_code))
        period_counter: int | None = None
        recovery_digest: bytes | None = None
        if factor_count == 1 and candidate.factor_key_version == self._factor_protector.key_version:
            if totp_code is not None:
                old_secret = self._factor_protector.decrypt(
                    account_id=account_id,
                    ciphertext=candidate.factor_ciphertext,
                )
                period_counter = self._totp.verify(
                    secret=old_secret,
                    code=totp_code,
                    now=now,
                    used_period_counters=candidate.used_period_counters,
                    algorithm=candidate.factor_algorithm,
                )
            else:
                recovery_digest = self._recovery_codes.match(
                    value=recovery_code or "",
                    active_lookup_digests=candidate.active_recovery_digests,
                )

        valid_factor = (period_counter is not None) != (recovery_digest is not None)
        if not password.verified or not valid_factor:
            self._record_invalid_credentials(account_id)
            return "invalid_credentials"

        new_secret = self._totp.generate_secret()
        encrypted = self._pending_factor_protector.encrypt(
            account_id=account_id,
            flow=TOTP_REPLACEMENT_FLOW,
            secret=new_secret,
        )
        setup = PendingSecuritySetup(
            account_id=account_id,
            flow=TOTP_REPLACEMENT_FLOW,
            status="pending",
            totp_secret_ciphertext=encrypted,
            key_version=self._pending_factor_protector.key_version,
            created_at=now,
            expires_at=now + TOTP_REPLACEMENT_TTL,
        )
        if not self._store.save_pending_setup(
            setup=setup,
            verified_totp_factor_id=(
                candidate.factor_id if period_counter is not None else None
            ),
            verified_totp_period_counter=period_counter,
            verified_recovery_code_digest=recovery_digest,
        ):
            return "unavailable"

        return PreparedTotpReplacement(
            provisioning_uri=self._totp.provisioning_uri(
                secret=new_secret,
                account_label=f"Cuenta administrativa {account_id}",
                issuer=TOTP_REPLACEMENT_ISSUER,
            ),
            manual_key=new_secret.decode("ascii"),
        )

    def _record_invalid_credentials(self, account_id: int) -> None:
        self._failures.record(account_id=account_id, operation="totp_replacement")
        self._record_failed_audit(account_id)

    def _record_failed_audit(self, account_id: int) -> None:
        self._audit.record(
            actor_account_id=account_id,
            action="totp_replacement",
            result="failed",
        )
