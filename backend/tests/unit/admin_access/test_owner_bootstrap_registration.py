"""T031 unit evidence for protected owner bootstrap registration."""

from __future__ import annotations

import base64

import pytest

from backend.app.application.admin_access.owner_bootstrap import (
    RegisterOwnerBootstrap,
)
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.authentication.admin_email_claim import (
    AdministrativeEmailClaimError,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
    ProtectedAdministrativeEmail,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
)


class RecordingOwnerBootstrapStore:
    def __init__(self) -> None:
        self.emails: list[ProtectedAdministrativeEmail] = []

    def register_inactive_owner(self, *, email: ProtectedAdministrativeEmail) -> None:
        self.emails.append(email)


def _protector() -> AdministrativeEmailProtector:
    return AdministrativeEmailProtector(
        key_ring=CryptographyKeyRing(
            CryptographyKeyConfiguration(
                root_key=SecretValue(
                    base64.urlsafe_b64encode(b"\x31" * 32).decode("ascii")
                ),
                key_version="v1",
            )
        ),
        secret_generator=SequenceSecretGenerator([b"\x32" * 12]),
    )


def test_t031_protects_the_prompted_email_before_registering_the_inactive_owner() -> None:
    store = RecordingOwnerBootstrapStore()

    RegisterOwnerBootstrap(store=store, email_protector=_protector()).register(
        email="  Synthetic.Owner@Example.TEST "
    )

    assert len(store.emails) == 1
    protected = store.emails[0]
    assert len(protected.lookup_digest) == 32
    assert b"synthetic.owner@example.test" not in protected.email_ciphertext


def test_t031_rejects_invalid_email_without_creating_an_owner() -> None:
    store = RecordingOwnerBootstrapStore()

    with pytest.raises(AdministrativeEmailClaimError):
        RegisterOwnerBootstrap(store=store, email_protector=_protector()).register(
            email="not-an-email"
        )

    assert store.emails == []
