"""T043 unit evidence for indistinguishable, non-consuming login validation."""

from datetime import datetime, timezone

import pytest

from backend.app.application.admin_access.login_validation import (
    AdministrativeLoginCandidate,
    INVALID_LOGIN_REJECTION,
    ValidateAdministrativeLogin,
)
from backend.app.application.clock import FixedClock
from backend.app.infrastructure.security.administrative_password_hashing import PasswordVerification


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
RECOVERY_DIGEST = b"\x43" * 32


class Store:
    def __init__(self, candidate):
        self.candidate = candidate

    def load_candidate(self, *, email_lookup_digest):
        return self.candidate if email_lookup_digest == b"digest" else None


class EmailLookup:
    def lookup_digest(self, value):
        if value != "owner@example.test":
            raise ValueError("invalid email")
        return b"digest"


class Passwords:
    def verify_and_upgrade(self, *, stored_hash, password):
        return PasswordVerification(password == "correct password", None)

    def verify_unknown_account(self, *, password):
        return PasswordVerification(False, None)


class FactorProtector:
    key_version = "v1"

    def decrypt(self, *, account_id, ciphertext):
        return b"JBSWY3DPEHPK3PXP"


class Totp:
    def verify(self, *, secret, code, now, used_period_counters=(), algorithm="SHA1"):
        return 123 if code == "123456" and 123 not in used_period_counters else None


class RecoveryCodes:
    def match(self, *, value, active_lookup_digests):
        return RECOVERY_DIGEST if value == "ABCD-EFGH-JKLM-NPQR" else None


class CredentialCheckGuard:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.account_ids = []

    def ensure_allowed(self, *, account_id):
        self.account_ids.append(account_id)
        return self.allowed


def _candidate(**changes):
    values = {
        "account_id": 7,
        "role": "owner",
        "status": "active",
        "password_hash": "stored",
        "factor_id": 9,
        "factor_ciphertext": b"ciphertext",
        "factor_key_version": "v1",
        "factor_algorithm": "SHA1",
        "used_period_counters": (),
        "active_recovery_digests": (RECOVERY_DIGEST,),
    }
    values.update(changes)
    return AdministrativeLoginCandidate(**values)


def _validator(candidate, *, guard=None, passwords=None):
    return ValidateAdministrativeLogin(
        store=Store(candidate),
        email_lookup=EmailLookup(),
        password_verifier=passwords or Passwords(),
        factor_protector=FactorProtector(),
        totp=Totp(),
        recovery_codes=RecoveryCodes(),
        credential_check_guard=guard or CredentialCheckGuard(),
        clock=FixedClock(NOW),
    )


def test_t043_accepts_password_with_exactly_one_valid_totp_without_consuming_it() -> None:
    outcome = _validator(_candidate()).validate(
        email="owner@example.test",
        password="correct password",
        totp_code="123456",
    )

    assert outcome.accepted
    assert outcome.validated is not None
    assert outcome.validated.totp_period_counter == 123
    assert outcome.validated.recovery_code_digest is None


def test_t043_accepts_password_with_exactly_one_valid_recovery_code_without_consuming_it() -> None:
    outcome = _validator(_candidate()).validate(
        email="owner@example.test",
        password="correct password",
        recovery_code="ABCD-EFGH-JKLM-NPQR",
    )

    assert outcome.accepted
    assert outcome.validated is not None
    assert outcome.validated.recovery_code_digest == RECOVERY_DIGEST
    assert outcome.validated.totp_period_counter is None


@pytest.mark.parametrize(
    ("candidate", "email", "password", "totp_code", "recovery_code"),
    (
        (_candidate(), "invalid", "correct password", "123456", None),
        (None, "owner@example.test", "correct password", "123456", None),
        (_candidate(status="pending"), "owner@example.test", "correct password", "123456", None),
        (_candidate(), "owner@example.test", "wrong password", "123456", None),
        (_candidate(), "owner@example.test", "correct password", "000000", None),
        (_candidate(), "owner@example.test", "correct password", None, "WRONG-CODE"),
        (_candidate(), "owner@example.test", "correct password", None, None),
        (_candidate(), "owner@example.test", "correct password", "123456", "ABCD-EFGH-JKLM-NPQR"),
        (_candidate(used_period_counters=(123,)), "owner@example.test", "correct password", "123456", None),
    ),
    ids=(
        "invalid-email",
        "unknown-account",
        "inactive-account",
        "wrong-password",
        "wrong-totp",
        "wrong-recovery",
        "missing-factor",
        "two-factors",
        "used-totp-period",
    ),
)
def test_t043_all_invalid_accounts_credentials_and_shapes_share_one_result(
    candidate,
    email,
    password,
    totp_code,
    recovery_code,
) -> None:
    outcome = _validator(candidate).validate(
        email=email,
        password=password,
        totp_code=totp_code,
        recovery_code=recovery_code,
    )

    assert not outcome.accepted
    assert outcome.validated is None
    assert outcome.rejection == INVALID_LOGIN_REJECTION
    assert password not in repr(outcome)
    if totp_code is not None:
        assert totp_code not in repr(outcome)
    if recovery_code is not None:
        assert recovery_code not in repr(outcome)


def test_t043_keeps_only_an_internal_account_reference_for_t044_failures() -> None:
    known = _validator(_candidate()).validate(
        email="owner@example.test",
        password="wrong password",
        totp_code="123456",
    )
    unknown = _validator(None).validate(
        email="owner@example.test",
        password="wrong password",
        totp_code="123456",
    )

    assert known.rejected_account_id == 7
    assert unknown.rejected_account_id is None
    assert "7" not in repr(known)


def test_t046_blocked_account_is_rejected_before_any_credential_verification() -> None:
    class TrackingPasswords(Passwords):
        def __init__(self) -> None:
            self.calls = []

        def verify_and_upgrade(self, *, stored_hash, password):
            self.calls.append((stored_hash, password))
            return super().verify_and_upgrade(
                stored_hash=stored_hash,
                password=password,
            )

    passwords = TrackingPasswords()
    guard = CredentialCheckGuard(allowed=False)
    outcome = _validator(
        _candidate(),
        guard=guard,
        passwords=passwords,
    ).validate(
        email="owner@example.test",
        password="correct password",
        totp_code="123456",
    )

    assert not outcome.accepted
    assert outcome.rejection == INVALID_LOGIN_REJECTION
    assert not outcome.records_failure
    assert guard.account_ids == [7]
    assert passwords.calls == []
