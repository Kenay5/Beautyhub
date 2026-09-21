"""Framework-independent invariants for opaque administrative sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, TypeAlias


SESSION_INACTIVITY_LIMIT = timedelta(minutes=30)
SESSION_ABSOLUTE_LIMIT = timedelta(hours=8)
AdminSessionStatus: TypeAlias = Literal["active", "invalidated"]


class AdminSessionInvariantError(ValueError):
    """Raised when an administrative session persistence record is invalid."""


@dataclass(frozen=True)
class AdminSession:
    """A server-side session that contains only opaque value digests."""

    account_id: int
    session_digest: bytes
    csrf_digest: bytes
    key_version: str
    created_at: datetime
    last_human_activity_at: datetime
    absolute_expires_at: datetime
    status: AdminSessionStatus
    invalidated_at: datetime | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise AdminSessionInvariantError(
                "administrative session account is invalid."
            )
        for digest in (self.session_digest, self.csrf_digest):
            if not isinstance(digest, bytes) or len(digest) != 32:
                raise AdminSessionInvariantError(
                    "administrative session digest is invalid."
                )
        if not isinstance(self.key_version, str) or not self.key_version.strip():
            raise AdminSessionInvariantError(
                "administrative session key version is invalid."
            )
        for instant in (
            self.created_at,
            self.last_human_activity_at,
            self.absolute_expires_at,
        ):
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise AdminSessionInvariantError("administrative session timestamp is invalid.")
        if not (
            self.created_at <= self.last_human_activity_at <= self.absolute_expires_at
        ):
            raise AdminSessionInvariantError("administrative session time range is invalid.")
        if self.absolute_expires_at != self.created_at + SESSION_ABSOLUTE_LIMIT:
            raise AdminSessionInvariantError("administrative session absolute expiry is invalid.")
        if self.status not in {"active", "invalidated"}:
            raise AdminSessionInvariantError("administrative session status is invalid.")
        if self.status == "active" and self.invalidated_at is not None:
            raise AdminSessionInvariantError("active administrative session is invalid.")
        if self.status == "invalidated" and self.invalidated_at is None:
            raise AdminSessionInvariantError("invalidated administrative session is invalid.")


def is_admin_session_valid(*, session: AdminSession, now: datetime) -> bool:
    """Reject at exact inactivity or absolute expiration, or after invalidation."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise AdminSessionInvariantError("administrative session clock instant is invalid.")
    if session.status != "active":
        return False
    return (
        now < session.last_human_activity_at + SESSION_INACTIVITY_LIMIT
        and now < session.absolute_expires_at
    )
