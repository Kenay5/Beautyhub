"""Administrative email normalization and persistence-shape invariants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from backend.app.domain.email_address import (
    EmailAddressValidationError,
    normalize_email_address,
)


AdminEmailClaimKind: TypeAlias = Literal["current", "reserved"]


class AdministrativeEmailClaimError(ValueError):
    """Raised when an administrative email claim is not safely shaped."""


def normalize_administrative_email_address(value: str) -> str:
    """Validate the approved email syntax and compare it case-insensitively."""

    try:
        return normalize_email_address(value).lower()
    except EmailAddressValidationError as error:
        raise AdministrativeEmailClaimError("administrative email is invalid.") from error


@dataclass(frozen=True)
class AdminEmailClaim:
    """A claim containing only protected email representations."""

    account_id: int
    kind: AdminEmailClaimKind
    lookup_digest: bytes
    email_ciphertext: bytes
    key_version: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise AdministrativeEmailClaimError("administrative email account is invalid.")
        if self.kind not in {"current", "reserved"}:
            raise AdministrativeEmailClaimError("administrative email claim kind is invalid.")
        if not isinstance(self.lookup_digest, bytes) or len(self.lookup_digest) != 32:
            raise AdministrativeEmailClaimError("administrative email digest is invalid.")
        if not isinstance(self.email_ciphertext, bytes) or not self.email_ciphertext:
            raise AdministrativeEmailClaimError("administrative email ciphertext is invalid.")
        if not isinstance(self.key_version, str) or not self.key_version:
            raise AdministrativeEmailClaimError("administrative email key version is invalid.")
