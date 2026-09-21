"""T037 unit evidence for resending and cancelling a pending staff invitation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.application.admin_access.security_links import (
    SecurityLinkLifecycle,
    StoredSecurityLink,
)
from backend.app.application.admin_access.staff_invitation import (
    ManageStaffInvitation,
    PendingStaffRecipient,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.audit.admin_audit_event import AdministrativeAuditEvent
from backend.app.domain.authentication.security_link import SecurityLink
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)


class RecordingAuditStore:
    def __init__(self) -> None:
        self.events: list[AdministrativeAuditEvent] = []

    def append(self, *, event: AdministrativeAuditEvent) -> None:
        self.events.append(event)


class InMemoryInvitationStore:
    def __init__(self) -> None:
        self.recipient = PendingStaffRecipient(
            account_id=12,
            email="synthetic.staff@example.test",
        )
        self.load_calls: list[int] = []
        self.cancel_calls: list[tuple[int, datetime]] = []

    def load_pending_staff_recipient(self, *, owner_account_id: int) -> PendingStaffRecipient:
        self.load_calls.append(owner_account_id)
        return self.recipient

    def cancel_pending_staff(self, *, owner_account_id: int, current_time: datetime) -> int:
        self.cancel_calls.append((owner_account_id, current_time))
        return self.recipient.account_id


@dataclass
class LinkRow:
    link_id: int
    link: SecurityLink
    status: str = "active"


class InMemoryLinkStore:
    def __init__(self) -> None:
        self.rows: list[LinkRow] = []

    def replace_active(self, *, link: SecurityLink) -> StoredSecurityLink:
        for row in self.rows:
            if row.link.account_id == link.account_id and row.status == "active":
                row.status = "invalidated"
        row = LinkRow(link_id=len(self.rows) + 1, link=link)
        self.rows.append(row)
        return StoredSecurityLink(
            link_id=row.link_id,
            account_id=link.account_id,
            purpose=link.purpose,
            expires_at=link.expires_at,
        )

    def inspect_active(self, **_: object) -> None:
        return None

    def consume_active(self, **_: object) -> None:
        return None


def _manager(
    invitation_store: InMemoryInvitationStore,
    link_store: InMemoryLinkStore,
    audit_store: RecordingAuditStore,
    tokens: tuple[bytes, ...],
) -> ManageStaffInvitation:
    key_ring = CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\xb1" * 32).decode("ascii")),
            key_version="v1",
        )
    )
    return ManageStaffInvitation(
        store=invitation_store,
        link_lifecycle=SecurityLinkLifecycle(
            store=link_store,
            clock=FixedClock(NOW),
            secret_generator=SequenceSecretGenerator(tokens),
            protector=SecurityLinkProtector(key_ring=key_ring),
        ),
        audit=RecordAdministrativeAuditEvent(
            store=audit_store,
            clock=FixedClock(NOW),
        ),
        clock=FixedClock(NOW),
    )


def test_t037_resend_replaces_the_old_invitation_with_a_new_24_hour_token() -> None:
    invitation_store = InMemoryInvitationStore()
    link_store = InMemoryLinkStore()
    audit_store = RecordingAuditStore()
    manager = _manager(
        invitation_store,
        link_store,
        audit_store,
        (b"\xb2" * 32, b"\xb3" * 32),
    )
    first = manager.resend(actor=AdministrativeActor(account_id=7, role="owner"))
    replacement = manager.resend(
        actor=AdministrativeActor(account_id=7, role="owner")
    )

    assert invitation_store.load_calls == [7, 7]
    assert [row.status for row in link_store.rows] == ["invalidated", "active"]
    assert all(row.link.purpose == "invitation" for row in link_store.rows)
    assert all(row.link.expires_at == NOW + timedelta(hours=24) for row in link_store.rows)
    assert first.issued_link.token != replacement.issued_link.token
    assert [event.result for event in audit_store.events] == ["succeeded", "succeeded"]
    assert all(event.action == "staff_invitation" for event in audit_store.events)


def test_t037_cancel_deactivates_the_pending_account_and_releases_it_for_replacement() -> None:
    invitation_store = InMemoryInvitationStore()
    link_store = InMemoryLinkStore()
    audit_store = RecordingAuditStore()

    _manager(invitation_store, link_store, audit_store, ()).cancel(
        actor=AdministrativeActor(account_id=7, role="owner")
    )

    assert invitation_store.cancel_calls == [(7, NOW)]
    assert audit_store.events == [
        AdministrativeAuditEvent(
            actor_account_id=7,
            action="staff_deactivation",
            result="succeeded",
            occurred_at=NOW,
            target_reference="admin_account:12",
        )
    ]


def test_t037_staff_cannot_resend_or_cancel_an_invitation() -> None:
    invitation_store = InMemoryInvitationStore()
    link_store = InMemoryLinkStore()
    audit_store = RecordingAuditStore()
    manager = _manager(invitation_store, link_store, audit_store, (b"\xb4" * 32,))
    staff = AdministrativeActor(account_id=8, role="staff")

    with pytest.raises(AdministrativeAuthorizationError):
        manager.resend(actor=staff)
    with pytest.raises(AdministrativeAuthorizationError):
        manager.cancel(actor=staff)

    assert invitation_store.load_calls == []
    assert invitation_store.cancel_calls == []
    assert [event.action for event in audit_store.events] == [
        "authorization_denied",
        "authorization_denied",
    ]
