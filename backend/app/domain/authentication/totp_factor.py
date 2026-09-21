"""Framework-independent invariants for active administrative TOTP factors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias


TotpFactorStatus: TypeAlias = Literal["active", "invalidated"]


class TotpFactorInvariantError(ValueError):
    """Raised when a persistent TOTP factor is not safely shaped."""


@dataclass(frozen=True)
class TotpFactor:
    """An active factor whose secret is recoverable only through approved encryption."""

    account_id: int
    secret_ciphertext: bytes | None
    key_version: str | None
    algorithm: str
    digits: int
    period_seconds: int
    status: TotpFactorStatus
    confirmed_at: datetime
    invalidated_at: datetime | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise TotpFactorInvariantError("TOTP factor account is invalid.")
        if self.algorithm not in {"SHA1", "SHA256", "SHA512"}:
            raise TotpFactorInvariantError("TOTP factor algorithm is invalid.")
        if self.digits != 6 or self.period_seconds != 30:
            raise TotpFactorInvariantError("TOTP factor parameters are invalid.")
        if self.status not in {"active", "invalidated"}:
            raise TotpFactorInvariantError("TOTP factor status is invalid.")
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise TotpFactorInvariantError("TOTP factor confirmation is invalid.")

        has_ciphertext = isinstance(self.secret_ciphertext, bytes) and bool(
            self.secret_ciphertext
        )
        has_key_version = isinstance(self.key_version, str) and bool(
            self.key_version.strip()
        )
        if self.status == "active":
            if not has_ciphertext or not has_key_version or self.invalidated_at is not None:
                raise TotpFactorInvariantError("active TOTP factor is invalid.")
        elif (
            self.secret_ciphertext is not None
            or self.key_version is not None
            or self.invalidated_at is None
        ):
            raise TotpFactorInvariantError("invalidated TOTP factor is invalid.")


@dataclass(frozen=True)
class TotpPeriodUse:
    """A committed TOTP counter use, never created for failed operations."""

    account_id: int
    factor_id: int
    period_counter: int
    consumed_at: datetime

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (self.account_id, self.factor_id)
        ):
            raise TotpFactorInvariantError("TOTP period account or factor is invalid.")
        if (
            isinstance(self.period_counter, bool)
            or not isinstance(self.period_counter, int)
            or self.period_counter < 0
        ):
            raise TotpFactorInvariantError("TOTP period counter is invalid.")
        if self.consumed_at.tzinfo is None or self.consumed_at.utcoffset() is None:
            raise TotpFactorInvariantError("TOTP period consumption is invalid.")
