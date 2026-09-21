"""Invariants for incomplete administrative security configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias


PendingSecuritySetupFlow: TypeAlias = Literal[
    "owner_activation", "staff_activation", "totp_replacement"
]
PendingSecuritySetupStatus: TypeAlias = Literal[
    "pending", "confirmed", "invalidated", "expired"
]


class PendingSecuritySetupInvariantError(ValueError):
    """Raised when an incomplete security setup is not safely shaped."""


@dataclass(frozen=True)
class PendingSecuritySetup:
    """A temporary encrypted TOTP setup that is not an active factor."""

    account_id: int
    flow: PendingSecuritySetupFlow
    status: PendingSecuritySetupStatus
    totp_secret_ciphertext: bytes | None
    key_version: str | None
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise PendingSecuritySetupInvariantError("pending setup account is invalid.")
        if self.flow not in {"owner_activation", "staff_activation", "totp_replacement"}:
            raise PendingSecuritySetupInvariantError("pending setup flow is invalid.")
        if self.status not in {"pending", "confirmed", "invalidated", "expired"}:
            raise PendingSecuritySetupInvariantError("pending setup status is invalid.")
        has_ciphertext = isinstance(self.totp_secret_ciphertext, bytes) and bool(
            self.totp_secret_ciphertext
        )
        has_key_version = isinstance(self.key_version, str) and bool(
            self.key_version.strip()
        )
        if self.status == "pending":
            if not has_ciphertext:
                raise PendingSecuritySetupInvariantError("pending setup secret is invalid.")
            if not has_key_version:
                raise PendingSecuritySetupInvariantError(
                    "pending setup key version is invalid."
                )
        elif self.totp_secret_ciphertext is not None or self.key_version is not None:
            raise PendingSecuritySetupInvariantError(
                "completed pending setup must not retain secret material."
            )
        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.created_at
        ):
            raise PendingSecuritySetupInvariantError("pending setup expiry is invalid.")
