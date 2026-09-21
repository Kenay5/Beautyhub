"""Application boundary for one-use administrative security links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from backend.app.application.clock import Clock
from backend.app.application.entropy import SecretGenerator
from backend.app.domain.authentication.security_link import (
    SecurityLink,
    SecurityLinkPurpose,
)
from backend.app.domain.time import normalize_instant
from backend.app.infrastructure.security.security_link_protection import (
    SECURITY_LINK_TOKEN_BYTES,
    SecurityLinkProtectionError,
    SecurityLinkProtector,
)


SECURITY_LINK_LIFETIMES: Final[dict[SecurityLinkPurpose, timedelta]] = {
    "initial_activation": timedelta(minutes=30),
    "invitation": timedelta(hours=24),
    "password_recovery": timedelta(minutes=30),
    "forced_password_reset": timedelta(minutes=30),
    "totp_replacement": timedelta(minutes=30),
    "email_change": timedelta(minutes=30),
}


@dataclass(frozen=True)
class StoredSecurityLink:
    """Minimum non-secret state required by a security-link flow."""

    link_id: int
    account_id: int
    purpose: SecurityLinkPurpose
    expires_at: datetime


@dataclass(frozen=True)
class IssuedSecurityLink:
    """A newly issued token returned once with its durable metadata."""

    token: bytes
    stored_link: StoredSecurityLink


class SecurityLinkStore(Protocol):
    """Atomically persist replacement and one-use link transitions."""

    def replace_active(self, *, link: SecurityLink) -> StoredSecurityLink:
        """Invalidate the prior account-purpose link and store the replacement."""

    def inspect_active(
        self, *, token_digest: bytes, purpose: SecurityLinkPurpose, now: datetime
    ) -> StoredSecurityLink | None:
        """Return a currently valid link without consuming it."""

    def consume_active(
        self, *, token_digest: bytes, purpose: SecurityLinkPurpose, now: datetime
    ) -> StoredSecurityLink | None:
        """Consume one valid link conditionally and return the single winner."""


class SecurityLinkLifecycle:
    """Apply the common issuance, inspection and consumption rules."""

    def __init__(
        self,
        *,
        store: SecurityLinkStore,
        clock: Clock,
        secret_generator: SecretGenerator,
        protector: SecurityLinkProtector,
    ) -> None:
        self._store = store
        self._clock = clock
        self._secret_generator = secret_generator
        self._protector = protector

    def issue(
        self, *, account_id: int, purpose: SecurityLinkPurpose
    ) -> IssuedSecurityLink:
        """Issue a fresh token and atomically replace the previous active link."""

        _require_account_id(account_id)
        lifetime = _lifetime_for(purpose)
        issued_at = normalize_instant(self._clock.now())
        token = self._secret_generator.token_bytes(SECURITY_LINK_TOKEN_BYTES)
        token_digest = self._protector.digest(token)
        stored_link = self._store.replace_active(
            link=SecurityLink(
                account_id=account_id,
                purpose=purpose,
                token_digest=token_digest,
                key_version=self._protector.key_version,
                issued_at=issued_at,
                expires_at=issued_at + lifetime,
                status="active",
                delivery_status="pending",
            )
        )
        return IssuedSecurityLink(token=token, stored_link=stored_link)

    def inspect(
        self, *, token: bytes, purpose: SecurityLinkPurpose
    ) -> StoredSecurityLink | None:
        """Inspect a valid link without changing its one-use state."""

        _lifetime_for(purpose)
        token_digest = self._safe_digest(token)
        if token_digest is None:
            return None
        return self._store.inspect_active(
            token_digest=token_digest,
            purpose=purpose,
            now=normalize_instant(self._clock.now()),
        )

    def consume(
        self, *, token: bytes, purpose: SecurityLinkPurpose
    ) -> StoredSecurityLink | None:
        """Conditionally consume a valid link inside the caller's transaction."""

        _lifetime_for(purpose)
        token_digest = self._safe_digest(token)
        if token_digest is None:
            return None
        return self._store.consume_active(
            token_digest=token_digest,
            purpose=purpose,
            now=normalize_instant(self._clock.now()),
        )

    def _safe_digest(self, token: bytes) -> bytes | None:
        try:
            return self._protector.digest(token)
        except SecurityLinkProtectionError:
            return None


def _lifetime_for(purpose: SecurityLinkPurpose) -> timedelta:
    try:
        return SECURITY_LINK_LIFETIMES[purpose]
    except KeyError as error:
        raise ValueError("security link purpose is invalid.") from error


def _require_account_id(account_id: int) -> None:
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("administrative account identifier is invalid.")
