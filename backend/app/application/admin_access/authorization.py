"""Server-derived administrative identity used by protected use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AdministrativeRole = Literal["owner", "staff"]


class AdministrativeAuthorizationError(PermissionError):
    """Raised when the server-authenticated actor lacks an approved capability."""


@dataclass(frozen=True)
class AdministrativeActor:
    """Minimal identity loaded from an authenticated server-side session."""

    account_id: int
    role: AdministrativeRole

    def __post_init__(self) -> None:
        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise ValueError("administrative actor identifier is invalid.")
        if self.role not in {"owner", "staff"}:
            raise ValueError("administrative actor role is invalid.")


def require_owner(*, actor: AdministrativeActor) -> None:
    """Allow account-management operations only to the authenticated owner."""

    if actor.role != "owner":
        raise AdministrativeAuthorizationError("administrative operation is forbidden.")
