"""Confirm a reserved administrative email through a one-use link."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.security_change_invalidation import InvalidateAfterSecurityChange
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.clock import Clock
from backend.app.domain.time import normalize_instant


@dataclass(frozen=True)
class EmailChangeConfirmationCandidate:
    account_id: int
    current_claim_id: int
    reserved_claim_id: int
    current_email: str = field(repr=False)
    reserved_email: str = field(repr=False)
    reserved_digest: bytes = field(repr=False)


@dataclass(frozen=True)
class EmailChangeConfirmationOutcome:
    status: str
    notices: tuple[tuple[int, str], ...] = field(default=(), repr=False)


class EmailChangeConsumptionConflict(RuntimeError):
    """Roll back a promotion if the confirmation link cannot be consumed."""


class EmailChangeConfirmationStore(Protocol):
    def lock_active_account(self, *, account_id: int) -> bool: ...
    def is_delivery_accepted(self, *, account_id: int, link_id: int) -> bool: ...
    def load_candidate(self, *, account_id: int) -> EmailChangeConfirmationCandidate | None: ...
    def promote_reserved(self, *, candidate: EmailChangeConfirmationCandidate) -> bool: ...
    def invalidate_conflicting_link(self, *, account_id: int, link_id: int, current_time: datetime) -> None: ...


@dataclass(frozen=True)
class ConfirmOwnAdministrativeEmailChange:
    store: EmailChangeConfirmationStore
    links: SecurityLinkLifecycle
    invalidator: InvalidateAfterSecurityChange
    audit: RecordAdministrativeAuditEvent
    notifications: RecordSecurityNotificationDelivery
    clock: Clock

    def confirm(self, *, token: bytes) -> EmailChangeConfirmationOutcome:
        located = self.links.locate(token=token, purpose="email_change")
        if located is None or not self.store.lock_active_account(account_id=located.account_id):
            return EmailChangeConfirmationOutcome("unavailable")

        inspected = self.links.inspect(token=token, purpose="email_change")
        if inspected is None or inspected.link_id != located.link_id:
            return EmailChangeConfirmationOutcome("unavailable")
        if not self.store.is_delivery_accepted(
            account_id=located.account_id, link_id=located.link_id
        ):
            return EmailChangeConfirmationOutcome("unavailable")

        candidate = self.store.load_candidate(account_id=located.account_id)
        if candidate is None or not self.store.promote_reserved(candidate=candidate):
            self.store.invalidate_conflicting_link(
                account_id=located.account_id,
                link_id=located.link_id,
                current_time=normalize_instant(self.clock.now()),
            )
            self.audit.record(
                actor_account_id=located.account_id,
                action="email_change",
                result="failed",
            )
            return EmailChangeConfirmationOutcome("unavailable")

        consumed = self.links.consume(token=token, purpose="email_change")
        if consumed is None or consumed.link_id != located.link_id:
            raise EmailChangeConsumptionConflict("email change link lost one-use consumption")

        self.invalidator.execute(account_id=located.account_id)
        self.audit.record(
            actor_account_id=located.account_id,
            action="email_change",
            result="succeeded",
        )
        reference = f"email_change:{located.account_id}:{located.link_id}"
        previous_notice = self.notifications.record(
            event="email_changed",
            template="email_changed_previous_notice",
            recipient=candidate.current_email,
            idempotency_reference=reference,
        )
        new_notice = self.notifications.record(
            event="email_changed",
            template="email_changed_new_notice",
            recipient=candidate.reserved_email,
            idempotency_reference=reference,
        )
        return EmailChangeConfirmationOutcome(
            "completed",
            notices=(
                (previous_notice.delivery_id, candidate.current_email),
                (new_notice.delivery_id, candidate.reserved_email),
            ),
        )
