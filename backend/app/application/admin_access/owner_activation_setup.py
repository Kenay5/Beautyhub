"""Prepare and abandon the unconfirmed owner activation setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.app.application.admin_access.pending_security_state import (
    DiscardPendingSecurityState,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import Clock
from backend.app.domain.authentication.pending_security_setup import PendingSecuritySetup
from backend.app.domain.time import normalize_instant
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator


OWNER_ACTIVATION_FLOW = "owner_activation"
OWNER_TOTP_ACCOUNT_LABEL = "Propietario"
OWNER_TOTP_ISSUER = "Manita de Gato"


class OwnerActivationSetupError(ValueError):
    """Raised through one generic result when the owner setup is unavailable."""


@dataclass(frozen=True)
class StoredPendingTotpSetup:
    """Encrypted pending setup state returned from persistence."""

    account_id: int
    ciphertext: bytes = field(repr=False)
    key_version: str


@dataclass(frozen=True)
class PreparedOwnerActivationSetup:
    """The secret material authorized only inside an unconfirmed setup flow."""

    provisioning_uri: str = field(repr=False)
    manual_key: str = field(repr=False)


class PendingTotpSetupStore(Protocol):
    """Persist at most one pending TOTP setup for one account and flow."""

    def create_or_get(
        self, *, setup: PendingSecuritySetup
    ) -> StoredPendingTotpSetup:
        """Return the existing pending setup or atomically create the candidate."""


class PrepareOwnerActivationSetup:
    """Inspect, but never consume, the initial link and prepare its TOTP secret."""

    def __init__(
        self,
        *,
        link_lifecycle: SecurityLinkLifecycle,
        setup_store: PendingTotpSetupStore,
        totp: TotpAuthenticator,
        protector: PendingTotpProtector,
        clock: Clock,
    ) -> None:
        self._link_lifecycle = link_lifecycle
        self._setup_store = setup_store
        self._totp = totp
        self._protector = protector
        self._clock = clock

    def prepare(self, *, token: bytes) -> PreparedOwnerActivationSetup:
        """Create or recover only the pending setup for one valid owner link."""

        link = self._link_lifecycle.inspect(
            token=token,
            purpose="initial_activation",
        )
        if link is None:
            raise OwnerActivationSetupError("owner activation setup is unavailable.")

        current_time = normalize_instant(self._clock.now())
        candidate_secret = self._totp.generate_secret()
        stored = self._setup_store.create_or_get(
            setup=PendingSecuritySetup(
                account_id=link.account_id,
                flow=OWNER_ACTIVATION_FLOW,
                status="pending",
                totp_secret_ciphertext=self._protector.encrypt(
                    account_id=link.account_id,
                    flow=OWNER_ACTIVATION_FLOW,
                    secret=candidate_secret,
                ),
                key_version=self._protector.key_version,
                created_at=current_time,
                expires_at=link.expires_at,
            )
        )
        secret = self._protector.decrypt(
            account_id=stored.account_id,
            flow=OWNER_ACTIVATION_FLOW,
            ciphertext=stored.ciphertext,
        )
        return PreparedOwnerActivationSetup(
            provisioning_uri=self._totp.provisioning_uri(
                secret=secret,
                account_label=OWNER_TOTP_ACCOUNT_LABEL,
                issuer=OWNER_TOTP_ISSUER,
            ),
            manual_key=secret.decode("ascii"),
        )


class AbandonOwnerActivationSetup:
    """Discard the pending TOTP secret while leaving the owner and link unchanged."""

    def __init__(
        self,
        *,
        link_lifecycle: SecurityLinkLifecycle,
        pending_state: DiscardPendingSecurityState,
    ) -> None:
        self._link_lifecycle = link_lifecycle
        self._pending_state = pending_state

    def abandon(self, *, token: bytes) -> None:
        """Discard setup material only when the same initial link remains valid."""

        link = self._link_lifecycle.inspect(
            token=token,
            purpose="initial_activation",
        )
        if link is None:
            raise OwnerActivationSetupError("owner activation setup is unavailable.")
        self._pending_state.abandoned_setup(
            account_id=link.account_id,
            flow=OWNER_ACTIVATION_FLOW,
        )
