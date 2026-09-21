"""Framework-independent invariants for one-use administrative links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias


SecurityLinkPurpose: TypeAlias = Literal[
    "initial_activation",
    "invitation",
    "password_recovery",
    "forced_password_reset",
    "totp_replacement",
    "email_change",
]
SecurityLinkStatus: TypeAlias = Literal["active", "consumed", "invalidated", "expired"]
SecurityLinkDeliveryStatus: TypeAlias = Literal[
    "pending", "accepted", "failed", "uncertain"
]


class SecurityLinkInvariantError(ValueError):
    """Raised when a security link is not safely shaped."""


@dataclass(frozen=True)
class SecurityLink:
    """A link represented by a digest and never by its plaintext token."""

    account_id: int
    purpose: SecurityLinkPurpose
    token_digest: bytes
    key_version: str
    issued_at: datetime
    expires_at: datetime
    status: SecurityLinkStatus
    delivery_status: SecurityLinkDeliveryStatus

    def __post_init__(self) -> None:
        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise SecurityLinkInvariantError("security link account is invalid.")
        if self.purpose not in {
            "initial_activation",
            "invitation",
            "password_recovery",
            "forced_password_reset",
            "totp_replacement",
            "email_change",
        }:
            raise SecurityLinkInvariantError("security link purpose is invalid.")
        if not isinstance(self.token_digest, bytes) or len(self.token_digest) != 32:
            raise SecurityLinkInvariantError("security link digest is invalid.")
        if not isinstance(self.key_version, str) or not self.key_version:
            raise SecurityLinkInvariantError("security link key version is invalid.")
        if (
            self.issued_at.tzinfo is None
            or self.issued_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.issued_at
        ):
            raise SecurityLinkInvariantError("security link expiry is invalid.")
        if self.status not in {"active", "consumed", "invalidated", "expired"}:
            raise SecurityLinkInvariantError("security link status is invalid.")
        if self.delivery_status not in {"pending", "accepted", "failed", "uncertain"}:
            raise SecurityLinkInvariantError("security link delivery status is invalid.")


def is_security_link_valid(
    *, status: SecurityLinkStatus, expires_at: datetime, now: datetime
) -> bool:
    """Return false at the exact expiry instant or for any non-active state."""

    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise SecurityLinkInvariantError("security link expiry must be aware.")
    if now.tzinfo is None or now.utcoffset() is None:
        raise SecurityLinkInvariantError("security link clock instant must be aware.")
    return status == "active" and now < expires_at
