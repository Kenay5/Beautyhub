"""T010 unit evidence for protected administrative email claims."""

from __future__ import annotations

import base64

import pytest

from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.authentication.admin_email_claim import (
    AdminEmailClaim,
    AdministrativeEmailClaimError,
    normalize_administrative_email_address,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtectionError,
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
)


def _key_ring(marker: int = 1) -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(
                base64.urlsafe_b64encode(bytes([marker]) * 32).decode("ascii")
            ),
            key_version="v1",
        )
    )


def test_t010_normalizes_case_and_outer_spaces_before_protection() -> None:
    protector = AdministrativeEmailProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator([b"\x01" * 12]),
    )

    protected = protector.protect("  Synthetic.Owner@Example.TEST ")

    assert normalize_administrative_email_address(
        "  Synthetic.Owner@Example.TEST "
    ) == "synthetic.owner@example.test"
    assert b"synthetic.owner@example.test" not in protected.email_ciphertext
    assert protector.decrypt(
        email_ciphertext=protected.email_ciphertext,
        key_version=protected.key_version,
    ) == "synthetic.owner@example.test"


def test_t010_uses_distinct_purpose_separated_email_digest_and_ciphertext() -> None:
    first = AdministrativeEmailProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator([b"\x02" * 12]),
    ).protect("synthetic.owner@example.test")
    second = AdministrativeEmailProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator([b"\x03" * 12]),
    ).protect("synthetic.owner@example.test")

    assert len(first.lookup_digest) == 32
    assert first.lookup_digest == second.lookup_digest
    assert first.email_ciphertext != second.email_ciphertext


def test_t010_rejects_tampered_or_wrong_version_email_ciphertext() -> None:
    protector = AdministrativeEmailProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator([b"\x04" * 12]),
    )
    protected = protector.protect("synthetic.owner@example.test")
    tampered = bytearray(protected.email_ciphertext)
    tampered[-1] ^= 1

    with pytest.raises(AdministrativeEmailProtectionError) as tampered_error:
        protector.decrypt(
            email_ciphertext=bytes(tampered), key_version=protected.key_version
        )
    with pytest.raises(AdministrativeEmailProtectionError):
        protector.decrypt(
            email_ciphertext=protected.email_ciphertext, key_version="v2"
        )

    assert "synthetic.owner@example.test" not in str(tampered_error.value)


@pytest.mark.parametrize(
    ("account_id", "kind", "lookup_digest", "email_ciphertext", "key_version"),
    (
        (0, "current", b"\x01" * 32, b"ciphertext", "v1"),
        (1, "other", b"\x01" * 32, b"ciphertext", "v1"),
        (1, "reserved", b"short", b"ciphertext", "v1"),
        (1, "reserved", b"\x01" * 32, b"", "v1"),
        (1, "reserved", b"\x01" * 32, b"ciphertext", ""),
    ),
)
def test_t010_rejects_unprotected_or_invalid_claim_shapes(
    account_id: int,
    kind: str,
    lookup_digest: bytes,
    email_ciphertext: bytes,
    key_version: str,
) -> None:
    with pytest.raises(AdministrativeEmailClaimError):
        AdminEmailClaim(
            account_id=account_id,
            kind=kind,  # type: ignore[arg-type]
            lookup_digest=lookup_digest,
            email_ciphertext=email_ciphertext,
            key_version=key_version,
        )
