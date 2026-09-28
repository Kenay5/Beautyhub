"""Create the one pending staff invitation from a server-authorized owner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
    require_owner,
)
from backend.app.application.admin_access.security_links import (
    IssuedSecurityLink,
    SecurityLinkLifecycle,
)
from backend.app.application.clock import Clock
from backend.app.application.security_link_delivery import send_security_link_notification
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.domain.time import normalize_instant
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
    ProtectedAdministrativeEmail,
)


class StaffInvitationError(ValueError):
    """Raised for a safely rejected staff-invitation request."""


@dataclass(frozen=True)
class PendingStaffRecipient:
    """A pending staff account and its email, visible only to the delivery flow."""

    account_id: int
    email: str = field(repr=False)


@dataclass(frozen=True)
class PendingStaffInvitation:
    """The durable pending account and its transient invitation delivery data."""

    account_id: int
    owner_account_id: int
    email: str = field(repr=False)
    issued_link: IssuedSecurityLink = field(repr=False)


@dataclass(frozen=True)
class StaffInvitationDeliveryOutcome:
    """A provider-independent result suitable for the authorized owner interface."""

    accepted: bool
    detail: str | None = None
    uncertain: bool = False


class StaffInvitationStore(Protocol):
    """Atomically claim an available email and create a pending staff account."""

    def create_pending_staff(
        self,
        *,
        owner_account_id: int,
        email: ProtectedAdministrativeEmail,
    ) -> int:
        """Return the new account id or reject without a partial account."""

    def load_pending_staff_recipient(
        self, *, owner_account_id: int
    ) -> PendingStaffRecipient:
        """Load and lock the only cancelable invitation for an authenticated owner."""

    def cancel_pending_staff(
        self, *, owner_account_id: int, current_time: datetime
    ) -> int:
        """Deactivate the pending staff account and release its email claim atomically."""


class StaffInvitationDeliveryStateStore(Protocol):
    """Persist only the safe state of an already-created invitation delivery."""

    def mark_delivery_accepted(self, *, link_id: int, current_time: datetime) -> None:
        """Mark a still-pending invitation link accepted by the provider."""

    def invalidate_failed_delivery(self, *, link_id: int, current_time: datetime) -> None:
        """Invalidate a failed link without changing its pending account."""


class CreateStaffInvitation:
    """Authorize an owner, reserve an email, and issue a 24-hour invitation."""

    def __init__(
        self,
        *,
        store: StaffInvitationStore,
        email_protector: AdministrativeEmailProtector,
        link_lifecycle: SecurityLinkLifecycle,
        audit: RecordAdministrativeAuditEvent,
    ) -> None:
        self._store = store
        self._email_protector = email_protector
        self._link_lifecycle = link_lifecycle
        self._audit = audit

    def invite(self, *, actor: AdministrativeActor, email: str) -> PendingStaffInvitation:
        """Create exactly one inactive-in-practice pending staff account.

        ``actor`` is deliberately a server-authentication value, never request data.
        The returned token remains transient for the delivery adapter and is excluded
        from representations so no caller can accidentally log it.
        """

        try:
            require_owner(actor=actor)
        except AdministrativeAuthorizationError:
            self._audit.record(
                actor_account_id=actor.account_id,
                action="authorization_denied",
                result="denied",
            )
            raise

        protected_email = self._email_protector.protect(email)
        try:
            account_id = self._store.create_pending_staff(
                owner_account_id=actor.account_id,
                email=protected_email,
            )
        except StaffInvitationError:
            raise

        issued_link = self._link_lifecycle.issue(
            account_id=account_id,
            purpose="invitation",
        )
        self._audit.record(
            actor_account_id=actor.account_id,
            action="staff_invitation",
            result="succeeded",
            target_reference=f"admin_account:{account_id}",
        )
        return PendingStaffInvitation(
            account_id=account_id,
            owner_account_id=actor.account_id,
            email=email.strip(),
            issued_link=issued_link,
        )


class DeliverStaffInvitation:
    """Deliver an issued invitation after commit and preserve its safe failure state."""

    def __init__(
        self,
        *,
        delivery_state_store: StaffInvitationDeliveryStateStore,
        email_sender: TransactionalNotificationPort,
        audit: RecordAdministrativeAuditEvent,
        clock: Clock,
    ) -> None:
        self._delivery_state_store = delivery_state_store
        self._email_sender = email_sender
        self._audit = audit
        self._clock = clock

    def deliver(
        self,
        *,
        invitation: PendingStaffInvitation,
        content: str,
    ) -> StaffInvitationDeliveryOutcome:
        """Send one opaque link without retaining it after a controlled failure."""

        link_id = invitation.issued_link.stored_link.link_id
        result = send_security_link_notification(
            sender=self._email_sender,
            notification=OutboundNotification(
                channel=EMAIL_CHANNEL,
                recipient=invitation.email,
                content=content,
                idempotency_key=f"security-link:{link_id}",
            )
        )
        current_time = normalize_instant(self._clock.now())
        if result.channel == EMAIL_CHANNEL and result.outcome == "accepted":
            self._delivery_state_store.mark_delivery_accepted(
                link_id=link_id,
                current_time=current_time,
            )
            return StaffInvitationDeliveryOutcome(accepted=True)

        if result.outcome == "uncertain":
            mark_uncertain = getattr(
                self._delivery_state_store, "mark_delivery_uncertain", None
            )
            if callable(mark_uncertain):
                mark_uncertain(link_id=link_id, current_time=current_time)
            return StaffInvitationDeliveryOutcome(
                accepted=False,
                uncertain=True,
                detail="No fue posible confirmar el envío. Puedes emitir un enlace nuevo.",
            )

        self._delivery_state_store.invalidate_failed_delivery(
            link_id=link_id,
            current_time=current_time,
        )
        self._audit.record(
            actor_account_id=invitation.owner_account_id,
            action="staff_invitation",
            result="failed",
            target_reference=f"admin_account:{invitation.account_id}",
        )
        return StaffInvitationDeliveryOutcome(
            accepted=False,
            detail="No se pudo enviar el correo. Inténtalo de nuevo.",
        )


class ManageStaffInvitation:
    """Allow only the owner to resend or cancel the one pending staff invitation."""

    def __init__(
        self,
        *,
        store: StaffInvitationStore,
        link_lifecycle: SecurityLinkLifecycle,
        audit: RecordAdministrativeAuditEvent,
        clock: Clock,
    ) -> None:
        self._store = store
        self._link_lifecycle = link_lifecycle
        self._audit = audit
        self._clock = clock

    def resend(self, *, actor: AdministrativeActor) -> PendingStaffInvitation:
        """Replace the active invitation token with a distinct 24-hour token."""

        self._require_owner(actor=actor)
        recipient = self._store.load_pending_staff_recipient(
            owner_account_id=actor.account_id
        )
        issued_link = self._link_lifecycle.issue(
            account_id=recipient.account_id,
            purpose="invitation",
        )
        self._audit.record(
            actor_account_id=actor.account_id,
            action="staff_invitation",
            result="succeeded",
            target_reference=f"admin_account:{recipient.account_id}",
        )
        return PendingStaffInvitation(
            account_id=recipient.account_id,
            owner_account_id=actor.account_id,
            email=recipient.email,
            issued_link=issued_link,
        )

    def cancel(self, *, actor: AdministrativeActor) -> None:
        """Invalidate the pending invitation and free the email for a replacement."""

        self._require_owner(actor=actor)
        account_id = self._store.cancel_pending_staff(
            owner_account_id=actor.account_id,
            current_time=normalize_instant(self._clock.now()),
        )
        self._audit.record(
            actor_account_id=actor.account_id,
            action="staff_deactivation",
            result="succeeded",
            target_reference=f"admin_account:{account_id}",
        )

    def _require_owner(self, *, actor: AdministrativeActor) -> None:
        try:
            require_owner(actor=actor)
        except AdministrativeAuthorizationError:
            self._audit.record(
                actor_account_id=actor.account_id,
                action="authorization_denied",
                result="denied",
            )
            raise
