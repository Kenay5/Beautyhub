"""Initial owner-activation link preparation and delivery outcome handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

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


class OwnerActivationLinkError(ValueError):
    """Raised when an initial owner-activation link cannot be issued safely."""


@dataclass(frozen=True)
class OwnerActivationRecipient:
    """The only recipient and account eligible for the initial activation flow."""

    account_id: int
    email: str = field(repr=False)


@dataclass(frozen=True)
class PreparedOwnerActivationLink:
    """One committed, pending delivery whose opaque token is held only transiently."""

    recipient: OwnerActivationRecipient = field(repr=False)
    issued_link: IssuedSecurityLink = field(repr=False)


class OwnerActivationRecipientStore(Protocol):
    """Load the still-inactive owner and its current protected email claim."""

    def load_inactive_owner_recipient(self) -> OwnerActivationRecipient | None:
        """Return the owner while retaining its account lock for link issuance."""


class SecurityLinkDeliveryStateStore(Protocol):
    """Persist only controlled delivery outcomes for one already-issued link."""

    def mark_delivery_accepted(self, *, link_id: int, current_time: datetime) -> None:
        """Mark an active, pending link accepted by the email provider."""

    def invalidate_failed_delivery(self, *, link_id: int, current_time: datetime) -> None:
        """Invalidate the failed link without reviving or touching a replacement."""


class PrepareOwnerActivationLink:
    """Create the owner link inside the transaction that reads the inactive owner."""

    def __init__(
        self,
        *,
        recipient_store: OwnerActivationRecipientStore,
        link_lifecycle: SecurityLinkLifecycle,
    ) -> None:
        self._recipient_store = recipient_store
        self._link_lifecycle = link_lifecycle

    def prepare(self) -> PreparedOwnerActivationLink:
        """Persist a 30-minute, pending initial-activation link before delivery."""

        recipient = self._recipient_store.load_inactive_owner_recipient()
        if recipient is None:
            raise OwnerActivationLinkError("owner activation link is unavailable.")
        issued_link = self._link_lifecycle.issue(
            account_id=recipient.account_id,
            purpose="initial_activation",
        )
        return PreparedOwnerActivationLink(
            recipient=recipient,
            issued_link=issued_link,
        )


class DeliverOwnerActivationLink:
    """Send one prepared link after commit and store its controlled outcome."""

    def __init__(
        self,
        *,
        delivery_state_store: SecurityLinkDeliveryStateStore,
        email_sender: TransactionalNotificationPort,
        clock: Clock,
    ) -> None:
        self._delivery_state_store = delivery_state_store
        self._email_sender = email_sender
        self._clock = clock

    def deliver(self, *, prepared_link: PreparedOwnerActivationLink, content: str) -> bool:
        """Persist the provider result and return whether the link was accepted."""

        link_id = prepared_link.issued_link.stored_link.link_id
        result = send_security_link_notification(
            sender=self._email_sender,
            notification=OutboundNotification(
                channel=EMAIL_CHANNEL,
                recipient=prepared_link.recipient.email,
                content=content,
                idempotency_key=f"security-link:{link_id}",
            )
        )
        current_time = normalize_instant(self._clock.now())
        if result.channel == EMAIL_CHANNEL and result.outcome == "accepted":
            self._delivery_state_store.mark_delivery_accepted(
                link_id=prepared_link.issued_link.stored_link.link_id,
                current_time=current_time,
            )
            return True

        if result.outcome == "uncertain":
            mark_uncertain = getattr(self._delivery_state_store, "mark_delivery_uncertain", None)
            if callable(mark_uncertain):
                mark_uncertain(link_id=link_id, current_time=current_time)
            return False

        self._delivery_state_store.invalidate_failed_delivery(
            link_id=link_id,
            current_time=current_time,
        )
        return False
