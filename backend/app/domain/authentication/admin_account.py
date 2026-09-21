"""Framework-independent invariants for administrative account identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypeAlias


AdminAccountRole: TypeAlias = Literal["owner", "staff"]
AdminAccountStatus: TypeAlias = Literal[
    "inactive", "pending", "active", "deactivated"
]
OwnerBootstrapStatus: TypeAlias = Literal["open", "closed"]

OWNER_ROLE: Final[AdminAccountRole] = "owner"
STAFF_ROLE: Final[AdminAccountRole] = "staff"
OWNER_BOOTSTRAP_OPEN: Final[OwnerBootstrapStatus] = "open"
OWNER_BOOTSTRAP_CLOSED: Final[OwnerBootstrapStatus] = "closed"


class AdministrativeAccountInvariantError(ValueError):
    """Raised when an administrative account shape is not approved."""


@dataclass(frozen=True)
class AdministrativeAccount:
    """An account identity without credentials or personally identifiable data."""

    role: AdminAccountRole
    status: AdminAccountStatus

    def __post_init__(self) -> None:
        if self.role == OWNER_ROLE and self.status in {"inactive", "active"}:
            return
        if self.role == STAFF_ROLE and self.status in {
            "pending",
            "active",
            "deactivated",
        }:
            return
        raise AdministrativeAccountInvariantError(
            "administrative account role and status are invalid."
        )


def validate_owner_bootstrap_transition(
    *,
    current_status: OwnerBootstrapStatus,
    next_status: OwnerBootstrapStatus,
    owner_account_id: int | None,
) -> None:
    """Permit closing the one bootstrap process but never reopening it."""

    if current_status not in {OWNER_BOOTSTRAP_OPEN, OWNER_BOOTSTRAP_CLOSED}:
        raise AdministrativeAccountInvariantError("owner bootstrap status is invalid.")
    if next_status not in {OWNER_BOOTSTRAP_OPEN, OWNER_BOOTSTRAP_CLOSED}:
        raise AdministrativeAccountInvariantError("owner bootstrap status is invalid.")
    if current_status == OWNER_BOOTSTRAP_CLOSED:
        raise AdministrativeAccountInvariantError("owner bootstrap is already closed.")
    if next_status == OWNER_BOOTSTRAP_CLOSED and (
        isinstance(owner_account_id, bool)
        or not isinstance(owner_account_id, int)
        or owner_account_id <= 0
    ):
        raise AdministrativeAccountInvariantError(
            "closed owner bootstrap requires an owner account."
        )
