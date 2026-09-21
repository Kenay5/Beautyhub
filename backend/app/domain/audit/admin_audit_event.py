"""Framework-independent minimum shape for administrative audit evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias


AdministrativeAuditAction: TypeAlias = Literal[
    "login",
    "account_locked",
    "logout",
    "account_activation",
    "staff_invitation",
    "staff_deactivation",
    "password_change",
    "password_recovery",
    "email_change",
    "totp_replacement",
    "recovery_code_regeneration",
    "appointment_created",
    "appointment_modified",
    "appointment_cancelled",
    "appointment_result_recorded",
    "appointment_private_code_resent",
    "availability_block_created",
    "availability_block_modified",
    "availability_block_deleted",
    "service_created",
    "service_modified",
    "service_activated",
    "service_deactivated",
    "authorization_denied",
]
AdministrativeAuditResult: TypeAlias = Literal["succeeded", "failed", "denied"]


class AdministrativeAuditEventInvariantError(ValueError):
    """Raised when an audit event would contain an unsafe or invalid shape."""


@dataclass(frozen=True)
class AdministrativeAuditEvent:
    """Minimum retained evidence with no copied private or credential values."""

    actor_account_id: int | None
    action: AdministrativeAuditAction
    result: AdministrativeAuditResult
    occurred_at: datetime
    target_reference: str | None

    def __post_init__(self) -> None:
        if self.actor_account_id is not None and (
            isinstance(self.actor_account_id, bool)
            or not isinstance(self.actor_account_id, int)
            or self.actor_account_id <= 0
        ):
            raise AdministrativeAuditEventInvariantError("audit actor is invalid.")
        if self.action not in _ACTIONS:
            raise AdministrativeAuditEventInvariantError("audit action is invalid.")
        if self.result not in {"succeeded", "failed", "denied"}:
            raise AdministrativeAuditEventInvariantError("audit result is invalid.")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise AdministrativeAuditEventInvariantError("audit timestamp is invalid.")
        if self.target_reference is not None and not _is_internal_reference(
            self.target_reference
        ):
            raise AdministrativeAuditEventInvariantError(
                "audit target reference is invalid."
            )


_ACTIONS = {
    "login",
    "account_locked",
    "logout",
    "account_activation",
    "staff_invitation",
    "staff_deactivation",
    "password_change",
    "password_recovery",
    "email_change",
    "totp_replacement",
    "recovery_code_regeneration",
    "appointment_created",
    "appointment_modified",
    "appointment_cancelled",
    "appointment_result_recorded",
    "appointment_private_code_resent",
    "availability_block_created",
    "availability_block_modified",
    "availability_block_deleted",
    "service_created",
    "service_modified",
    "service_activated",
    "service_deactivated",
    "authorization_denied",
}
_TARGET_KINDS = {"appointment", "availability_block", "service", "admin_account"}


def _is_internal_reference(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    kind, separator, identifier = value.partition(":")
    return (
        separator == ":"
        and bool(kind)
        and kind.isascii()
        and kind[0].isalpha()
        and all(character.islower() or character.isdigit() or character == "_" for character in kind)
        and 1 <= len(kind) <= 40
        and kind in _TARGET_KINDS
        and identifier.isascii()
        and identifier.isdecimal()
        and str(int(identifier)) == identifier
    )
