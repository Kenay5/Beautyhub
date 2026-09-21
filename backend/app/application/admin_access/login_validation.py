"""Validate administrative login credentials without consuming or creating state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from backend.app.application.clock import Clock
from backend.app.domain.time import normalize_instant


INVALID_LOGIN_REJECTION = "invalid_credentials"


@dataclass(frozen=True)
class AdministrativeLoginCandidate:
    account_id: int
    role: Literal["owner", "staff"]
    status: str
    password_hash: str = field(repr=False)
    factor_id: int | None
    factor_ciphertext: bytes | None = field(default=None, repr=False)
    factor_key_version: str | None = None
    factor_algorithm: str | None = None
    used_period_counters: tuple[int, ...] = ()
    active_recovery_digests: tuple[bytes, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class ValidatedAdministrativeLogin:
    """Internal proof passed to T044; it is never a public login response."""

    account_id: int
    role: Literal["owner", "staff"]
    factor_id: int
    totp_period_counter: int | None = None
    recovery_code_digest: bytes | None = field(default=None, repr=False)
    upgraded_password_hash: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        selected_factors = sum(
            value is not None
            for value in (self.totp_period_counter, self.recovery_code_digest)
        )
        if selected_factors != 1:
            raise ValueError("validated login must reference exactly one factor.")


@dataclass(frozen=True)
class AdministrativeLoginValidationOutcome:
    validated: ValidatedAdministrativeLogin | None = field(default=None, repr=False)
    rejection: str | None = None
    rejected_account_id: int | None = field(default=None, repr=False)
    records_failure: bool = field(default=True, repr=False)

    @property
    def accepted(self) -> bool:
        return self.validated is not None and self.rejection is None


class AdministrativeLoginStore(Protocol):
    def load_candidate(self, *, email_lookup_digest: bytes) -> AdministrativeLoginCandidate | None: ...


class EmailLookupProtector(Protocol):
    def lookup_digest(self, value: str) -> bytes: ...


class PasswordVerifier(Protocol):
    def verify_and_upgrade(self, *, stored_hash: str, password: str): ...
    def verify_unknown_account(self, *, password: str): ...


class TotpSecretProtector(Protocol):
    key_version: str
    def decrypt(self, *, account_id: int, ciphertext: bytes) -> bytes: ...


class TotpVerifier(Protocol):
    def verify(self, *, secret: bytes, code: str, now: datetime, used_period_counters=(), algorithm: str = "SHA1") -> int | None: ...


class RecoveryCodeMatcher(Protocol):
    def match(self, *, value: str, active_lookup_digests) -> bytes | None: ...


class AdministrativeCredentialCheckGuard(Protocol):
    def ensure_allowed(self, *, account_id: int) -> bool: ...


class ValidateAdministrativeLogin:
    """Return one generic rejection or an unconsumed internal credential proof."""

    def __init__(
        self,
        *,
        store: AdministrativeLoginStore,
        email_lookup: EmailLookupProtector,
        password_verifier: PasswordVerifier,
        factor_protector: TotpSecretProtector,
        totp: TotpVerifier,
        recovery_codes: RecoveryCodeMatcher,
        credential_check_guard: AdministrativeCredentialCheckGuard,
        clock: Clock,
    ) -> None:
        self._store = store
        self._email_lookup = email_lookup
        self._password_verifier = password_verifier
        self._factor_protector = factor_protector
        self._totp = totp
        self._recovery_codes = recovery_codes
        self._credential_check_guard = credential_check_guard
        self._clock = clock

    def validate(
        self,
        *,
        email: str,
        password: str,
        totp_code: str | None = None,
        recovery_code: str | None = None,
    ) -> AdministrativeLoginValidationOutcome:
        selected_factors = sum(value is not None for value in (totp_code, recovery_code))
        shape_is_valid = selected_factors == 1

        try:
            digest = self._email_lookup.lookup_digest(email)
            candidate = self._store.load_candidate(email_lookup_digest=digest)
        except (TypeError, ValueError):
            candidate = None

        if (
            candidate is not None
            and candidate.status == "active"
            and not self._credential_check_guard.ensure_allowed(
                account_id=candidate.account_id
            )
        ):
            return self._rejected(
                account_id=candidate.account_id,
                records_failure=False,
            )

        try:
            verification = (
                self._password_verifier.verify_and_upgrade(
                    stored_hash=candidate.password_hash,
                    password=password,
                )
                if candidate is not None
                else self._password_verifier.verify_unknown_account(password=password)
            )
        except (TypeError, ValueError):
            return self._rejected(
                account_id=None if candidate is None else candidate.account_id
            )

        if (
            not shape_is_valid
            or candidate is None
            or candidate.status != "active"
            or not verification.verified
            or candidate.factor_id is None
            or candidate.factor_ciphertext is None
            or candidate.factor_key_version != self._factor_protector.key_version
        ):
            return self._rejected(
                account_id=None if candidate is None else candidate.account_id
            )

        try:
            if totp_code is not None:
                secret = self._factor_protector.decrypt(
                    account_id=candidate.account_id,
                    ciphertext=candidate.factor_ciphertext,
                )
                period = self._totp.verify(
                    secret=secret,
                    code=totp_code,
                    now=normalize_instant(self._clock.now()),
                    used_period_counters=candidate.used_period_counters,
                    algorithm=candidate.factor_algorithm or "SHA1",
                )
                if period is None:
                    return self._rejected(account_id=candidate.account_id)
                proof = ValidatedAdministrativeLogin(
                    account_id=candidate.account_id,
                    role=candidate.role,
                    factor_id=candidate.factor_id,
                    totp_period_counter=period,
                    upgraded_password_hash=verification.upgraded_hash,
                )
            else:
                matched_digest = self._recovery_codes.match(
                    value=recovery_code or "",
                    active_lookup_digests=candidate.active_recovery_digests,
                )
                if matched_digest is None:
                    return self._rejected(account_id=candidate.account_id)
                proof = ValidatedAdministrativeLogin(
                    account_id=candidate.account_id,
                    role=candidate.role,
                    factor_id=candidate.factor_id,
                    recovery_code_digest=matched_digest,
                    upgraded_password_hash=verification.upgraded_hash,
                )
        except (TypeError, ValueError):
            return self._rejected(account_id=candidate.account_id)

        return AdministrativeLoginValidationOutcome(validated=proof)

    @staticmethod
    def _rejected(
        *,
        account_id: int | None,
        records_failure: bool = True,
    ) -> AdministrativeLoginValidationOutcome:
        return AdministrativeLoginValidationOutcome(
            rejection=INVALID_LOGIN_REJECTION,
            rejected_account_id=account_id,
            records_failure=records_failure,
        )
