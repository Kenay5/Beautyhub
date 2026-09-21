"""T011 unit evidence for link expiry and protected pending setup material."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.authentication.pending_security_setup import (
    PendingSecuritySetup,
    PendingSecuritySetupInvariantError,
)
from backend.app.domain.authentication.security_link import (
    SecurityLink,
    SecurityLinkInvariantError,
    is_security_link_valid,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import (
    PendingTotpProtectionError,
    PendingTotpProtector,
)
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtectionError,
    SecurityLinkProtector,
)
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(
                base64.urlsafe_b64encode(b"\x11" * 32).decode("ascii")
            ),
            key_version="v1",
        )
    )


def test_t011_hashes_exactly_256_bit_opaque_tokens() -> None:
    protector = SecurityLinkProtector(key_ring=_key_ring())
    token = b"\x12" * 32

    digest = protector.digest(token)

    assert len(digest) == 32
    assert token not in digest
    assert digest == protector.digest(token)
    with pytest.raises(SecurityLinkProtectionError):
        protector.digest(b"short")


def test_t011_rejects_a_link_at_exact_expiry_and_for_non_active_states() -> None:
    issued_at = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    expires_at = issued_at + timedelta(minutes=30)

    assert is_security_link_valid(
        status="active", expires_at=expires_at, now=expires_at - timedelta(seconds=1)
    )
    assert not is_security_link_valid(
        status="active", expires_at=expires_at, now=expires_at
    )
    assert not is_security_link_valid(
        status="expired", expires_at=expires_at, now=expires_at - timedelta(seconds=1)
    )


def test_t011_encrypts_pending_totp_material_with_the_approved_subkey() -> None:
    protector = PendingTotpProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator([b"\x13" * 12]),
    )
    secret = b"synthetic-totp-secret"

    ciphertext = protector.encrypt(
        account_id=7, flow="owner_activation", secret=secret
    )

    assert secret not in ciphertext
    assert (
        protector.decrypt(
            account_id=7, flow="owner_activation", ciphertext=ciphertext
        )
        == secret
    )
    tampered = bytearray(ciphertext)
    tampered[-1] ^= 1
    with pytest.raises(PendingTotpProtectionError):
        protector.decrypt(
            account_id=7, flow="owner_activation", ciphertext=bytes(tampered)
        )


def test_t011_rejects_invalid_pending_setup_shape() -> None:
    instant = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    with pytest.raises(PendingSecuritySetupInvariantError):
        PendingSecuritySetup(
            account_id=1,
            flow="owner_activation",
            status="pending",
            totp_secret_ciphertext=b"ciphertext",
            key_version="v1",
            created_at=instant,
            expires_at=instant,
        )


def test_t011_rejects_invalid_security_link_shape() -> None:
    instant = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    with pytest.raises(SecurityLinkInvariantError):
        SecurityLink(
            account_id=1,
            purpose="invitation",
            token_digest=b"short",
            key_version="v1",
            issued_at=instant,
            expires_at=instant + timedelta(hours=24),
            status="active",
            delivery_status="pending",
        )
