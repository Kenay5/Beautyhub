"""T012 unit evidence for protected factors and one-time credentials."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest

from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.authentication.recovery_code import (
    RecoveryCode,
    RecoveryCodeInvariantError,
)
from backend.app.domain.authentication.totp_factor import (
    TotpFactor,
    TotpFactorInvariantError,
    TotpPeriodUse,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.totp_factor_protection import (
    TotpFactorProtectionError,
    TotpFactorProtector,
)
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x21" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def test_t012_encrypts_an_active_totp_secret_for_its_account_only() -> None:
    protector = TotpFactorProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator([b"\x22" * 12]),
    )
    secret = b"synthetic-base32-totp-secret"

    ciphertext = protector.encrypt(account_id=7, secret=secret)

    assert secret not in ciphertext
    assert protector.decrypt(account_id=7, ciphertext=ciphertext) == secret
    with pytest.raises(TotpFactorProtectionError):
        protector.decrypt(account_id=8, ciphertext=ciphertext)


def test_t012_keeps_recovery_codes_as_irreversible_separated_digests() -> None:
    protector = RecoveryCodeProtector(key_ring=_key_ring())
    code = "ABCD-EFGH-JKLM-NPQR"

    digest = protector.digest(code)

    assert len(digest) == 32
    assert code.encode("ascii") not in digest
    assert digest == protector.digest(code)


def test_t012_requires_an_active_factor_to_retain_encrypted_secret_material() -> None:
    instant = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)

    with pytest.raises(TotpFactorInvariantError):
        TotpFactor(
            account_id=1,
            secret_ciphertext=None,
            key_version=None,
            algorithm="SHA1",
            digits=6,
            period_seconds=30,
            status="active",
            confirmed_at=instant,
            invalidated_at=None,
        )


def test_t012_rejects_recovery_code_state_without_its_one_time_timestamp() -> None:
    with pytest.raises(RecoveryCodeInvariantError):
        RecoveryCode(
            account_id=1,
            lookup_digest=b"\x31" * 32,
            key_version="v1",
            position=1,
            status="used",
            used_at=None,
            invalidated_at=None,
        )


def test_t012_rejects_negative_totp_period_counter() -> None:
    with pytest.raises(TotpFactorInvariantError):
        TotpPeriodUse(
            account_id=1,
            factor_id=1,
            period_counter=-1,
            consumed_at=datetime(2030, 6, 15, 10, tzinfo=timezone.utc),
        )
