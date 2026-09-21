"""Framework-independent invariants for non-recoverable recovery codes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias


RecoveryCodeStatus: TypeAlias = Literal["active", "used", "invalidated"]


class RecoveryCodeInvariantError(ValueError):
    """Raised when a recovery-code persistence record is not safely shaped."""


@dataclass(frozen=True)
class RecoveryCode:
    """One recovery code represented only by its keyed lookup digest."""

    account_id: int
    lookup_digest: bytes
    key_version: str
    position: int
    status: RecoveryCodeStatus
    used_at: datetime | None
    invalidated_at: datetime | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise RecoveryCodeInvariantError("recovery code account is invalid.")
        if not isinstance(self.lookup_digest, bytes) or len(self.lookup_digest) != 32:
            raise RecoveryCodeInvariantError("recovery code digest is invalid.")
        if not isinstance(self.key_version, str) or not self.key_version.strip():
            raise RecoveryCodeInvariantError("recovery code key version is invalid.")
        if (
            isinstance(self.position, bool)
            or not isinstance(self.position, int)
            or not 1 <= self.position <= 10
        ):
            raise RecoveryCodeInvariantError("recovery code position is invalid.")
        if self.status not in {"active", "used", "invalidated"}:
            raise RecoveryCodeInvariantError("recovery code status is invalid.")
        if self.status == "active" and (
            self.used_at is not None or self.invalidated_at is not None
        ):
            raise RecoveryCodeInvariantError("active recovery code is invalid.")
        if self.status == "used" and (
            self.used_at is None or self.invalidated_at is not None
        ):
            raise RecoveryCodeInvariantError("used recovery code is invalid.")
        if self.status == "invalidated" and self.invalidated_at is None:
            raise RecoveryCodeInvariantError("invalidated recovery code is invalid.")
        for instant in (self.used_at, self.invalidated_at):
            if instant is not None and (
                instant.tzinfo is None or instant.utcoffset() is None
            ):
                raise RecoveryCodeInvariantError("recovery code timestamp is invalid.")
