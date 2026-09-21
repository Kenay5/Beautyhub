"""T033 unit evidence for preparing an unconfirmed owner activation."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.admin_access.owner_activation_setup import (
    AbandonOwnerActivationSetup,
    OwnerActivationSetupError,
    PrepareOwnerActivationSetup,
    StoredPendingTotpSetup,
)
from backend.app.application.admin_access.security_links import StoredSecurityLink
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.authentication.pending_security_setup import PendingSecuritySetup
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)
TOKEN = b"\x71" * 32


class InspectOnlyLifecycle:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.inspections: list[tuple[bytes, str]] = []

    def inspect(self, *, token: bytes, purpose: str):
        self.inspections.append((token, purpose))
        if not self.available:
            return None
        return StoredSecurityLink(
            link_id=11,
            account_id=7,
            purpose="initial_activation",
            expires_at=NOW + timedelta(minutes=30),
        )


class InMemoryPendingSetupStore:
    def __init__(self) -> None:
        self.persisted: PendingSecuritySetup | None = None
        self.candidates: list[PendingSecuritySetup] = []

    def create_or_get(self, *, setup: PendingSecuritySetup) -> StoredPendingTotpSetup:
        self.candidates.append(setup)
        if self.persisted is None:
            self.persisted = setup
        return StoredPendingTotpSetup(
            account_id=self.persisted.account_id,
            ciphertext=self.persisted.totp_secret_ciphertext or b"",
            key_version=self.persisted.key_version or "",
        )


class RecordingPendingState:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def abandoned_setup(self, *, account_id: int, flow: str) -> None:
        self.calls.append((account_id, flow))


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x72" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def _preparer(lifecycle: InspectOnlyLifecycle, store: InMemoryPendingSetupStore):
    return PrepareOwnerActivationSetup(
        link_lifecycle=lifecycle,  # type: ignore[arg-type]
        setup_store=store,
        totp=TotpAuthenticator(
            secret_generator=SequenceSecretGenerator((b"\x73" * 20, b"\x74" * 20))
        ),
        protector=PendingTotpProtector(
            key_ring=_key_ring(),
            secret_generator=SequenceSecretGenerator((b"\x75" * 12, b"\x76" * 12)),
        ),
        clock=FixedClock(NOW),
    )


def test_t033_prepares_one_reusable_totp_secret_without_consuming_the_link() -> None:
    lifecycle = InspectOnlyLifecycle()
    store = InMemoryPendingSetupStore()
    preparer = _preparer(lifecycle, store)

    first = preparer.prepare(token=TOKEN)
    second = preparer.prepare(token=TOKEN)

    assert first.manual_key == second.manual_key
    assert first.provisioning_uri.startswith("otpauth://totp/Manita%20de%20Gato:Propietario?")
    assert "digits=6" not in first.provisioning_uri
    assert "period=30" not in first.provisioning_uri
    assert lifecycle.inspections == [
        (TOKEN, "initial_activation"),
        (TOKEN, "initial_activation"),
    ]
    assert store.persisted is not None
    assert store.persisted.status == "pending"
    assert store.persisted.expires_at == NOW + timedelta(minutes=30)
    assert first.manual_key.encode("ascii") not in (store.persisted.totp_secret_ciphertext or b"")
    assert "manual_key" not in repr(first)


def test_t033_rejects_an_unavailable_link_before_persisting_any_setup() -> None:
    lifecycle = InspectOnlyLifecycle(available=False)
    store = InMemoryPendingSetupStore()

    with pytest.raises(OwnerActivationSetupError, match="unavailable"):
        _preparer(lifecycle, store).prepare(token=TOKEN)

    assert store.persisted is None
    assert store.candidates == []


def test_t033_abandon_discards_pending_material_without_consuming_the_link() -> None:
    lifecycle = InspectOnlyLifecycle()
    pending_state = RecordingPendingState()

    AbandonOwnerActivationSetup(
        link_lifecycle=lifecycle,  # type: ignore[arg-type]
        pending_state=pending_state,  # type: ignore[arg-type]
    ).abandon(token=TOKEN)

    assert lifecycle.inspections == [(TOKEN, "initial_activation")]
    assert pending_state.calls == [(7, "owner_activation")]
