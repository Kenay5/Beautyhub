"""Owner-authorized forced password reset for the active staff account."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
    require_owner,
)
from backend.app.application.admin_access.security_links import IssuedSecurityLink, SecurityLinkLifecycle


class ForcedPasswordResetUnavailable(ValueError):
    """Raised when no active staff account can be reset safely."""


@dataclass(frozen=True)
class ActiveStaffRecipient:
    account_id: int
    email: str = field(repr=False)


@dataclass(frozen=True)
class ForcedPasswordReset:
    owner_account_id: int
    staff_account_id: int
    recipient_email: str = field(repr=False)
    issued_link: IssuedSecurityLink = field(repr=False)


class ForceStaffPasswordResetStore(Protocol):
    def invalidate_staff_access_and_load_recipient(
        self, *, owner_account_id: int
    ) -> ActiveStaffRecipient: ...


class ForceStaffPasswordReset:
    """Invalidate staff credentials and sessions before delivering a reset link."""

    def __init__(
        self,
        *,
        store: ForceStaffPasswordResetStore,
        link_lifecycle: SecurityLinkLifecycle,
        audit: RecordAdministrativeAuditEvent,
    ) -> None:
        self._store = store
        self._links = link_lifecycle
        self._audit = audit

    def force(self, *, actor: AdministrativeActor) -> ForcedPasswordReset:
        try:
            require_owner(actor=actor)
        except AdministrativeAuthorizationError:
            self._audit.record(
                actor_account_id=actor.account_id,
                action="authorization_denied",
                result="denied",
            )
            raise

        recipient = self._store.invalidate_staff_access_and_load_recipient(
            owner_account_id=actor.account_id
        )
        issued = self._links.issue(
            account_id=recipient.account_id,
            purpose="forced_password_reset",
        )
        self._audit.record(
            actor_account_id=actor.account_id,
            action="password_recovery",
            result="succeeded",
            target_reference=f"admin_account:{recipient.account_id}",
        )
        return ForcedPasswordReset(
            owner_account_id=actor.account_id,
            staff_account_id=recipient.account_id,
            recipient_email=recipient.email,
            issued_link=issued,
        )
