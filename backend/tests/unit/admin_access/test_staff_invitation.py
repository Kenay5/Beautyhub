"""T035 unit evidence for owner-only pending staff invitations."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone

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
    CreateStaffInvitation,
    StaffInvitationError,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.audit.admin_audit_event import AdministrativeAuditEvent
from backend.app.domain.authentication.security_link import SecurityLink
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
    ProtectedAdministrativeEmail,
)
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


class RecordingInvitationStore:
    def __init__(self, *, rejection: bool = False) -> None:
        self.rejection = rejection
        self.calls: list[tuple[int, ProtectedAdministrativeEmail]] = []

    def create_pending_staff(
        self, *, owner_account_id: int, email: ProtectedAdministrativeEmail
    ) -> int:
        if self.rejection:
            raise StaffInvitationError("unavailable")
        self.calls.append((owner_account_id, email))
        return 12


@dataclass
class LinkRow:
    link_id: int
    link: SecurityLink


class InMemoryLinkStore:
    def __init__(self) -> None:
        self.rows: list[LinkRow] = []

    def replace_active(self, *, link: SecurityLink) -> StoredSecurityLink:
        self.rows.append(LinkRow(link_id=len(self.rows) + 1, link=link))
        return StoredSecurityLink(
            link_id=len(self.rows),
            account_id=link.account_id,
            purpose=link.purpose,
            expires_at=link.expires_at,
        )

    def inspect_active(self, **_: object) -> None:
        return None

    def consume_active(self, **_: object) -> None:
        return None


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x81" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def _inviter(
    invitation_store: RecordingInvitationStore,
    audit_store: RecordingAuditStore,
    link_store: InMemoryLinkStore,
) -> CreateStaffInvitation:
    key_ring = _key_ring()
    return CreateStaffInvitation(
        store=invitation_store,
        email_protector=AdministrativeEmailProtector(
            key_ring=key_ring,
            secret_generator=SequenceSecretGenerator((b"\x82" * 12,)),
        ),
        link_lifecycle=SecurityLinkLifecycle(
            store=link_store,
            clock=FixedClock(NOW),
            secret_generator=SequenceSecretGenerator((b"\x83" * 32,)),
            protector=SecurityLinkProtector(key_ring=key_ring),
        ),
        audit=RecordAdministrativeAuditEvent(
            store=audit_store,
            clock=FixedClock(NOW),
        ),
    )


def test_t035_owner_claims_a_protected_available_email_and_issues_a_24_hour_link() -> None:
    invitation_store = RecordingInvitationStore()
    audit_store = RecordingAuditStore()
    link_store = InMemoryLinkStore()

    invitation = _inviter(invitation_store, audit_store, link_store).invite(
        actor=AdministrativeActor(account_id=7, role="owner"),
        email="  Synthetic.Staff@Example.TEST ",
    )

    assert invitation.account_id == 12
    assert invitation.email == "Synthetic.Staff@Example.TEST"
    assert len(invitation_store.calls) == 1
    owner_id, protected_email = invitation_store.calls[0]
    assert owner_id == 7
    assert len(protected_email.lookup_digest) == 32
    assert b"synthetic.staff@example.test" not in protected_email.email_ciphertext
    assert link_store.rows[0].link.purpose == "invitation"
    assert link_store.rows[0].link.account_id == 12
    assert link_store.rows[0].link.expires_at == NOW.replace(day=6)
    assert invitation.issued_link.token not in link_store.rows[0].link.token_digest
    assert audit_store.events == [
        AdministrativeAuditEvent(
            actor_account_id=7,
            action="staff_invitation",
            result="succeeded",
            occurred_at=NOW,
            target_reference="admin_account:12",
        )
    ]
    assert "email" not in repr(invitation)
    assert "token" not in repr(invitation)


def test_t035_staff_cannot_claim_an_email_or_issue_an_invitation() -> None:
    invitation_store = RecordingInvitationStore()
    audit_store = RecordingAuditStore()
    link_store = InMemoryLinkStore()

    with pytest.raises(AdministrativeAuthorizationError):
        _inviter(invitation_store, audit_store, link_store).invite(
            actor=AdministrativeActor(account_id=8, role="staff"),
            email="synthetic.staff@example.test",
        )

    assert invitation_store.calls == []
    assert link_store.rows == []
    assert [(event.action, event.result, event.actor_account_id) for event in audit_store.events] == [
        ("authorization_denied", "denied", 8)
    ]


def test_t035_unavailable_email_leaves_no_link_or_success_audit() -> None:
    invitation_store = RecordingInvitationStore(rejection=True)
    audit_store = RecordingAuditStore()
    link_store = InMemoryLinkStore()

    with pytest.raises(StaffInvitationError):
        _inviter(invitation_store, audit_store, link_store).invite(
            actor=AdministrativeActor(account_id=7, role="owner"),
            email="synthetic.staff@example.test",
        )

    assert link_store.rows == []
    assert audit_store.events == []
