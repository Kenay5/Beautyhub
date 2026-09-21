"""T034 unit evidence for atomic owner activation decisions."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pyotp

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.owner_activation import (
    CompleteOwnerActivation,
    LockedOwnerActivation,
)
from backend.app.application.admin_access.security_links import StoredSecurityLink
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)
TOKEN = b"\x91" * 32
PASSWORD = "synthetic owner phrase 2033"


class InspectLifecycle:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.inspections: list[tuple[bytes, str]] = []

    def inspect(self, *, token: bytes, purpose: str):
        self.inspections.append((token, purpose))
        if not self.available:
            return None
        return StoredSecurityLink(
            link_id=13,
            account_id=7,
            purpose="initial_activation",
            expires_at=NOW + timedelta(minutes=30),
        )


class ActivationStore:
    def __init__(self, candidate: LockedOwnerActivation | None) -> None:
        self.candidate = candidate
        self.discarded: list[LockedOwnerActivation] = []
        self.activations: list[dict[str, object]] = []

    def lock_candidate(self, **_: object) -> LockedOwnerActivation | None:
        return self.candidate

    def discard_pending(self, *, candidate, current_time) -> None:
        del current_time
        self.discarded.append(candidate)

    def activate(self, **values: object) -> None:
        self.activations.append(values)


class BlockedPasswords:
    def __init__(self, blocked: bool = False) -> None:
        self.blocked = blocked

    def contains(self, password: str) -> bool:
        assert password == PASSWORD
        return self.blocked


class AuditStore:
    def __init__(self) -> None:
        self.events = []

    def append(self, *, event) -> None:
        self.events.append(event)


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x92" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def _prepared_secret() -> tuple[bytes, bytes]:
    secret = TotpAuthenticator(
        secret_generator=SequenceSecretGenerator((b"\x93" * 20,))
    ).generate_secret()
    ciphertext = PendingTotpProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator((b"\x94" * 12,)),
    ).encrypt(account_id=7, flow="owner_activation", secret=secret)
    return secret, ciphertext


def _recovery_entropy() -> tuple[bytes, ...]:
    return tuple(
        bytes((offset + position) % 32 for position in range(16))
        for offset in range(10)
    )


def _completer(
    *,
    lifecycle: InspectLifecycle,
    store: ActivationStore,
    audit_store: AuditStore,
    blocked: bool = False,
) -> CompleteOwnerActivation:
    key_ring = _key_ring()
    return CompleteOwnerActivation(
        link_lifecycle=lifecycle,  # type: ignore[arg-type]
        store=store,
        blocked_passwords=BlockedPasswords(blocked),
        password_hasher=AdministrativePasswordHasher(),
        pending_totp_protector=PendingTotpProtector(
            key_ring=key_ring,
            secret_generator=SequenceSecretGenerator(()),
        ),
        factor_protector=TotpFactorProtector(
            key_ring=key_ring,
            secret_generator=SequenceSecretGenerator((b"\x95" * 12,)),
        ),
        totp=TotpAuthenticator(secret_generator=SequenceSecretGenerator(())),
        recovery_codes=RecoveryCodeService(
            secret_generator=SequenceSecretGenerator(_recovery_entropy()),
            protector=RecoveryCodeProtector(key_ring=key_ring),
        ),
        audit=RecordAdministrativeAuditEvent(
            store=audit_store,
            clock=FixedClock(NOW),
        ),
        clock=FixedClock(NOW),
    )


def _candidate(ciphertext: bytes) -> LockedOwnerActivation:
    return LockedOwnerActivation(
        link_id=13,
        account_id=7,
        setup_id=17,
        pending_totp_ciphertext=ciphertext,
        pending_key_version="v1",
    )


def test_t034_builds_all_credentials_and_audits_without_creating_a_session() -> None:
    secret, ciphertext = _prepared_secret()
    store = ActivationStore(_candidate(ciphertext))
    audit_store = AuditStore()
    password_hasher = AdministrativePasswordHasher()
    code = pyotp.TOTP(secret.decode("ascii"), digits=6, interval=30).at(NOW)

    outcome = _completer(
        lifecycle=InspectLifecycle(),
        store=store,
        audit_store=audit_store,
    ).complete(token=TOKEN, password=PASSWORD, totp_code=code)

    assert outcome.activated
    assert len(outcome.recovery_codes) == 10
    assert len(set(outcome.recovery_codes)) == 10
    assert all(len(value) == 19 and value.count("-") == 3 for value in outcome.recovery_codes)
    assert store.discarded == []
    assert len(store.activations) == 1
    activation = store.activations[0]
    assert password_hasher.verify_and_upgrade(
        stored_hash=activation["password_hash"],  # type: ignore[arg-type]
        password=PASSWORD,
    ).verified
    assert len(activation["recovery_codes"]) == 10  # type: ignore[arg-type]
    assert activation["factor"].secret_ciphertext != secret  # type: ignore[union-attr]
    assert audit_store.events[0].action == "account_activation"
    assert audit_store.events[0].actor_account_id == 7
    assert "session" not in activation
    assert PASSWORD not in repr(outcome)
    assert outcome.recovery_codes[0] not in repr(outcome)


def test_t034_rejects_bad_totp_and_discards_the_pending_secret() -> None:
    secret, ciphertext = _prepared_secret()
    store = ActivationStore(_candidate(ciphertext))
    audit_store = AuditStore()
    valid_code = pyotp.TOTP(secret.decode("ascii"), digits=6, interval=30).at(NOW)
    invalid_code = ("1" if valid_code[0] != "1" else "2") + valid_code[1:]

    outcome = _completer(
        lifecycle=InspectLifecycle(),
        store=store,
        audit_store=audit_store,
    ).complete(token=TOKEN, password=PASSWORD, totp_code=invalid_code)

    assert outcome.rejection == "unavailable"
    assert store.discarded == [store.candidate]
    assert store.activations == []
    assert audit_store.events == []


def test_t034_rejects_blocked_password_and_discards_the_pending_secret() -> None:
    _, ciphertext = _prepared_secret()
    store = ActivationStore(_candidate(ciphertext))

    outcome = _completer(
        lifecycle=InspectLifecycle(),
        store=store,
        audit_store=AuditStore(),
        blocked=True,
    ).complete(token=TOKEN, password=PASSWORD, totp_code="123456")

    assert outcome.rejection == "invalid_password"
    assert store.discarded == [store.candidate]
    assert store.activations == []


def test_t034_unavailable_link_never_locks_or_changes_activation_state() -> None:
    _, ciphertext = _prepared_secret()
    store = ActivationStore(_candidate(ciphertext))
    lifecycle = InspectLifecycle(available=False)

    outcome = _completer(
        lifecycle=lifecycle,
        store=store,
        audit_store=AuditStore(),
    ).complete(token=TOKEN, password=PASSWORD, totp_code="123456")

    assert outcome.rejection == "unavailable"
    assert store.discarded == []
    assert store.activations == []
