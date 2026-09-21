"""T024 evidence for authenticated encryption and separated secret fingerprints."""

from __future__ import annotations

import base64

import pytest

from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtectionError,
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.admin_session_protection import (
    AdminSessionProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import (
    PendingTotpProtectionError,
    PendingTotpProtector,
)
from backend.app.infrastructure.security.public_request_subject import (
    PublicRequestSubjectProtector,
)
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.security.totp_factor_protection import (
    TotpFactorProtectionError,
    TotpFactorProtector,
)
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x71" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def test_t024_encrypts_email_and_totp_with_authenticated_context() -> None:
    key_ring = _key_ring()
    email_protector = AdministrativeEmailProtector(
        key_ring=key_ring,
        secret_generator=SequenceSecretGenerator([b"\x72" * 12]),
    )
    factor_protector = TotpFactorProtector(
        key_ring=key_ring,
        secret_generator=SequenceSecretGenerator([b"\x73" * 12]),
    )
    pending_protector = PendingTotpProtector(
        key_ring=key_ring,
        secret_generator=SequenceSecretGenerator([b"\x74" * 12]),
    )

    protected_email = email_protector.protect("Synthetic.Owner@Example.TEST")
    factor_ciphertext = factor_protector.encrypt(account_id=7, secret=b"totp-secret")
    pending_ciphertext = pending_protector.encrypt(
        account_id=7, flow="owner_activation", secret=b"pending-totp-secret"
    )

    assert email_protector.decrypt(
        email_ciphertext=protected_email.email_ciphertext,
        key_version=protected_email.key_version,
    ) == "synthetic.owner@example.test"
    assert factor_protector.decrypt(account_id=7, ciphertext=factor_ciphertext) == b"totp-secret"
    assert pending_protector.decrypt(
        account_id=7, flow="owner_activation", ciphertext=pending_ciphertext
    ) == b"pending-totp-secret"
    with pytest.raises(TotpFactorProtectionError):
        factor_protector.decrypt(account_id=8, ciphertext=factor_ciphertext)
    with pytest.raises(PendingTotpProtectionError):
        pending_protector.decrypt(
            account_id=7, flow="staff_activation", ciphertext=pending_ciphertext
        )
    with pytest.raises(AdministrativeEmailProtectionError):
        email_protector.decrypt(
            email_ciphertext=protected_email.email_ciphertext,
            key_version="v2",
        )


def test_t024_uses_distinct_non_reversible_fingerprints_for_each_purpose() -> None:
    key_ring = _key_ring()
    opaque_token = b"\x75" * 32

    link_digest = SecurityLinkProtector(key_ring=key_ring).digest(opaque_token)
    session_protector = AdminSessionProtector(key_ring=key_ring)
    session_digest = session_protector.digest_session_token(opaque_token)
    csrf_digest = session_protector.digest_csrf_token(opaque_token)
    recovery_digest = RecoveryCodeProtector(key_ring=key_ring).digest("RECOVERY-CODE")
    email_digest = AdministrativeEmailProtector(
        key_ring=key_ring,
        secret_generator=SequenceSecretGenerator([b"\x76" * 12]),
    ).protect("synthetic.owner@example.test").lookup_digest
    ip_digest = PublicRequestSubjectProtector(key_ring=key_ring).fingerprint_ip(
        "2001:db8::1"
    )

    digests = {
        link_digest,
        session_digest,
        csrf_digest,
        recovery_digest,
        email_digest,
        ip_digest,
    }
    assert len(digests) == 6
    assert all(len(digest) == 32 for digest in digests)
    assert opaque_token not in link_digest
    assert opaque_token not in session_digest
    assert b"synthetic.owner@example.test" not in email_digest
    assert b"2001:db8::1" not in ip_digest
