"""Server-derived administrative identity used by protected use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


AdministrativeRole = Literal["owner", "staff"]
AdministrativeCapability = Literal[
    "manage_own_account_security",
    "operate_appointments",
    "retry_appointment_notifications",
    "manage_services_and_prices",
    "manage_staff_accounts",
    "view_administrative_history",
]

_CAPABILITIES_BY_ROLE: dict[AdministrativeRole, frozenset[str]] = {
    "owner": frozenset(
        {
            "manage_own_account_security",
            "operate_appointments",
            "retry_appointment_notifications",
            "manage_services_and_prices",
            "manage_staff_accounts",
            "view_administrative_history",
        }
    ),
    "staff": frozenset(
        {
            "manage_own_account_security",
            "operate_appointments",
            "retry_appointment_notifications",
        }
    ),
}


class AdministrativeAuthorizationError(PermissionError):
    """Raised when the server-authenticated actor lacks an approved capability."""


class AuthorizationDenialRecorder(Protocol):
    """Record the minimum evidence for an authenticated permission denial."""

    def record(
        self,
        *,
        actor_account_id: int | None,
        action: Literal["authorization_denied"],
        result: Literal["denied"],
    ) -> None: ...


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

    require_capability(actor=actor, capability="manage_staff_accounts")


def has_capability(
    *, actor: AdministrativeActor, capability: AdministrativeCapability
) -> bool:
    """Return a decision from the server-loaded role and approved capability map."""

    if not isinstance(actor, AdministrativeActor):
        return False
    role_capabilities = _CAPABILITIES_BY_ROLE.get(actor.role)
    return role_capabilities is not None and capability in role_capabilities


def require_capability(
    *,
    actor: AdministrativeActor,
    capability: AdministrativeCapability,
    audit: AuthorizationDenialRecorder | None = None,
) -> None:
    """Reject a capability before a protected use case reads or mutates data."""

    if not has_capability(actor=actor, capability=capability):
        if audit is not None and isinstance(actor, AdministrativeActor):
            audit.record(
                actor_account_id=actor.account_id,
                action="authorization_denied",
                result="denied",
            )
        raise AdministrativeAuthorizationError("administrative operation is forbidden.")
