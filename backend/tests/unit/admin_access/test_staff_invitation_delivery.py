"""T036 unit evidence for safe failed staff-invitation delivery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.security_links import (
    IssuedSecurityLink,
    StoredSecurityLink,
)
from backend.app.application.admin_access.staff_invitation import (
    DeliverStaffInvitation,
    PendingStaffInvitation,
)
from backend.app.application.clock import FixedClock
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.domain.audit.admin_audit_event import AdministrativeAuditEvent


NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)
TOKEN = b"\xa1" * 32


class RecordingDeliveryStateStore:
    def __init__(self) -> None:
        self.accepted: list[tuple[int, datetime]] = []
        self.failed: list[tuple[int, datetime]] = []

    def mark_delivery_accepted(self, *, link_id: int, current_time: datetime) -> None:
        self.accepted.append((link_id, current_time))

    def invalidate_failed_delivery(self, *, link_id: int, current_time: datetime) -> None:
        self.failed.append((link_id, current_time))


class RecordingAuditStore:
    def __init__(self) -> None:
        self.events: list[AdministrativeAuditEvent] = []

    def append(self, *, event: AdministrativeAuditEvent) -> None:
        self.events.append(event)


class FailingEmailSender:
    def __init__(self) -> None:
        self.notifications: list[OutboundNotification] = []

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.notifications.append(notification)
        return NotificationSendResult.failed(EMAIL_CHANNEL)


def _invitation() -> PendingStaffInvitation:
    return PendingStaffInvitation(
        account_id=12,
        owner_account_id=7,
        email="synthetic.staff@example.test",
        issued_link=IssuedSecurityLink(
            token=TOKEN,
            stored_link=StoredSecurityLink(
                link_id=23,
                account_id=12,
                purpose="invitation",
                expires_at=NOW + timedelta(hours=24),
            ),
        ),
    )


def test_t036_failed_delivery_invalidates_only_the_link_and_returns_a_safe_owner_message() -> None:
    delivery_state = RecordingDeliveryStateStore()
    audit_store = RecordingAuditStore()
    sender = FailingEmailSender()

    outcome = DeliverStaffInvitation(
        delivery_state_store=delivery_state,
        email_sender=sender,
        audit=RecordAdministrativeAuditEvent(
            store=audit_store,
            clock=FixedClock(NOW),
        ),
        clock=FixedClock(NOW),
    ).deliver(
        invitation=_invitation(),
        content="/admin/security-link#token=opaque-test-token",
    )

    assert outcome.accepted is False
    assert outcome.detail == "No se pudo enviar el correo. Inténtalo de nuevo."
    assert delivery_state.accepted == []
    assert delivery_state.failed == [(23, NOW)]
    assert sender.notifications[0].recipient == "synthetic.staff@example.test"
    assert len(audit_store.events) == 1
    event = audit_store.events[0]
    assert (event.actor_account_id, event.action, event.result, event.target_reference) == (
        7,
        "staff_invitation",
        "failed",
        "admin_account:12",
    )
    assert TOKEN.hex() not in repr(event)
    assert "opaque-test-token" not in repr(event)
