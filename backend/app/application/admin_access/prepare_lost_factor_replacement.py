"""Prepare a new factor behind a valid lost-factor replacement link."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from backend.app.application.admin_access.prepare_totp_replacement import (
    TOTP_REPLACEMENT_FLOW,
    TOTP_REPLACEMENT_ISSUER,
    TotpReplacementCandidate,
    TotpReplacementStore,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import Clock
from backend.app.domain.authentication.pending_security_setup import PendingSecuritySetup
from backend.app.domain.time import normalize_instant


TOTP_REPLACEMENT_SETUP_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class StoredLostFactorTotpSetup:
    ciphertext: bytes = field(repr=False)
    key_version: str
    expires_at: datetime


class LostFactorTotpSetupStore(Protocol):
    def load_candidate(self, *, account_id: int) -> TotpReplacementCandidate | None: ...

    def save_pending_setup_for_link(
        self, *, setup: PendingSecuritySetup, link_id: int
    ) -> StoredLostFactorTotpSetup | None: ...


class PendingTotpSecretProtector(Protocol):
    key_version: str

    def encrypt(self, *, account_id: int, flow: str, secret: bytes) -> bytes: ...

    def decrypt(self, *, account_id: int, flow: str, ciphertext: bytes) -> bytes: ...


class TotpSetupGenerator(Protocol):
    def generate_secret(self) -> bytes: ...

    def provisioning_uri(self, *, secret: bytes, account_label: str, issuer: str) -> str: ...


@dataclass(frozen=True)
class PreparedLostFactorTotpSetup:
    provisioning_uri: str = field(repr=False)
    manual_key: str = field(repr=False)


class PrepareLostFactorTotpReplacement:
    """Inspect, but do not consume, the link while leaving old credentials active."""

    def __init__(
        self,
        *,
        link_lifecycle: SecurityLinkLifecycle,
        setup_store: LostFactorTotpSetupStore,
        pending_protector: PendingTotpSecretProtector,
        totp: TotpSetupGenerator,
        clock: Clock,
    ) -> None:
        self._links = link_lifecycle
        self._store = setup_store
        self._pending = pending_protector
        self._totp = totp
        self._clock = clock

    def prepare(self, *, token: bytes) -> PreparedLostFactorTotpSetup:
        located = self._links.locate(token=token, purpose="totp_replacement")
        if located is None:
            raise ValueError("lost-factor replacement link is unavailable.")

        candidate = self._store.load_candidate(account_id=located.account_id)
        if candidate is None:
            raise ValueError("lost-factor replacement setup is unavailable.")

        link = self._links.inspect(token=token, purpose="totp_replacement")
        if link is None or link.link_id != located.link_id:
            raise ValueError("lost-factor replacement link is unavailable.")

        now = normalize_instant(self._clock.now())
        expires_at = min(link.expires_at, now + TOTP_REPLACEMENT_SETUP_TTL)
        secret = self._totp.generate_secret()
        setup = PendingSecuritySetup(
            account_id=link.account_id,
            flow=TOTP_REPLACEMENT_FLOW,
            status="pending",
            totp_secret_ciphertext=self._pending.encrypt(
                account_id=link.account_id,
                flow=TOTP_REPLACEMENT_FLOW,
                secret=secret,
            ),
            key_version=self._pending.key_version,
            created_at=now,
            expires_at=expires_at,
        )
        stored = self._store.save_pending_setup_for_link(
            setup=setup,
            link_id=link.link_id,
        )
        if stored is None:
            raise ValueError("lost-factor replacement link is unavailable.")

        stored_secret = self._pending.decrypt(
            account_id=link.account_id,
            flow=TOTP_REPLACEMENT_FLOW,
            ciphertext=stored.ciphertext,
        )
        return PreparedLostFactorTotpSetup(
            provisioning_uri=self._totp.provisioning_uri(
                secret=stored_secret,
                account_label=f"Cuenta administrativa {candidate.account_id}",
                issuer=TOTP_REPLACEMENT_ISSUER,
            ),
            manual_key=stored_secret.decode("ascii"),
        )
