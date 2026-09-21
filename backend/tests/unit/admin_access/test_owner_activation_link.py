"""T032 unit evidence for the initial owner-activation link workflow."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.admin_access.owner_activation_link import (
    DeliverOwnerActivationLink,
    OwnerActivationRecipient,
    PrepareOwnerActivationLink,
)
from backend.app.application.admin_access.security_links import (
    IssuedSecurityLink,
    SecurityLinkLifecycle,
    StoredSecurityLink,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.domain.authentication.security_link import SecurityLink
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)


@dataclass
class LinkRow:
    link_id: int
    link: SecurityLink
    status: str = "active"
    delivery_status: str = "pending"


class InMemoryLinkStore:
    def __init__(self) -> None:
        self.rows: list[LinkRow] = []

    def replace_active(self, *, link: SecurityLink) -> StoredSecurityLink:
        for row in self.rows:
            if (
                row.link.account_id == link.account_id
                and row.link.purpose == link.purpose
                and row.status == "active"
            ):
                row.status = "invalidated"
        row = LinkRow(link_id=len(self.rows) + 1, link=link)
        self.rows.append(row)
        return StoredSecurityLink(
            link_id=row.link_id,
            account_id=link.account_id,
            purpose=link.purpose,
            expires_at=link.expires_at,
        )

    def inspect_active(self, **_: object) -> StoredSecurityLink | None:
        return None

    def consume_active(self, **_: object) -> StoredSecurityLink | None:
        return None

    def mark_delivery_accepted(self, *, link_id: int, current_time: datetime) -> None:
        del current_time
        self._row(link_id).delivery_status = "accepted"

    def invalidate_failed_delivery(self, *, link_id: int, current_time: datetime) -> None:
        del current_time
        row = self._row(link_id)
        row.status = "invalidated"
        row.delivery_status = "failed"

    def _row(self, link_id: int) -> LinkRow:
        return next(row for row in self.rows if row.link_id == link_id)


class InMemoryOwnerRecipientStore:
    def __init__(self) -> None:
        self.recipient = OwnerActivationRecipient(
            account_id=7,
            email="synthetic.owner@example.test",
        )

    def load_inactive_owner_recipient(self) -> OwnerActivationRecipient | None:
        return self.recipient


class ControlledEmailSender:
    def __init__(self, *, outcome: str) -> None:
        self.outcome = outcome
        self.notifications: list[OutboundNotification] = []

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.notifications.append(notification)
        return NotificationSendResult(channel=EMAIL_CHANNEL, outcome=self.outcome)  # type: ignore[arg-type]


def _lifecycle(store: InMemoryLinkStore, tokens: tuple[bytes, ...]) -> SecurityLinkLifecycle:
    key_ring = CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x51" * 32).decode("ascii")),
            key_version="v1",
        )
    )
    return SecurityLinkLifecycle(
        store=store,
        clock=FixedClock(NOW),
        secret_generator=SequenceSecretGenerator(tokens),
        protector=SecurityLinkProtector(key_ring=key_ring),
    )


def test_t032_issues_one_opaque_30_minute_initial_activation_link() -> None:
    store = InMemoryLinkStore()

    prepared = PrepareOwnerActivationLink(
        recipient_store=InMemoryOwnerRecipientStore(),
        link_lifecycle=_lifecycle(store, (b"\x52" * 32,)),
    ).prepare()

    assert prepared.issued_link.stored_link.expires_at == NOW + timedelta(minutes=30)
    assert prepared.issued_link.token not in store.rows[0].link.token_digest
    assert store.rows[0].link.purpose == "initial_activation"
    assert store.rows[0].status == "active"
    assert store.rows[0].delivery_status == "pending"


def test_t032_accepts_delivery_without_exposing_the_token_outside_the_message() -> None:
    store = InMemoryLinkStore()
    prepared = PrepareOwnerActivationLink(
        recipient_store=InMemoryOwnerRecipientStore(),
        link_lifecycle=_lifecycle(store, (b"\x53" * 32,)),
    ).prepare()
    sender = ControlledEmailSender(outcome="accepted")

    accepted = DeliverOwnerActivationLink(
        delivery_state_store=store,
        email_sender=sender,
        clock=FixedClock(NOW),
    ).deliver(
        prepared_link=prepared,
        content="/admin/security-link#token=opaque-test-token",
    )

    assert accepted
    assert store.rows[0].delivery_status == "accepted"
    assert sender.notifications[0].recipient == "synthetic.owner@example.test"
    assert sender.notifications[0].content == "/admin/security-link#token=opaque-test-token"
    assert "token" not in repr(prepared)


def test_t032_invalidates_a_failed_link_and_allows_a_distinct_reissue() -> None:
    store = InMemoryLinkStore()
    preparer = PrepareOwnerActivationLink(
        recipient_store=InMemoryOwnerRecipientStore(),
        link_lifecycle=_lifecycle(store, (b"\x54" * 32, b"\x55" * 32)),
    )
    failed_link = preparer.prepare()

    accepted = DeliverOwnerActivationLink(
        delivery_state_store=store,
        email_sender=ControlledEmailSender(outcome="failed"),
        clock=FixedClock(NOW),
    ).deliver(prepared_link=failed_link, content="/admin/security-link#token=failed")

    replacement = preparer.prepare()

    assert not accepted
    assert store.rows[0].status == "invalidated"
    assert store.rows[0].delivery_status == "failed"
    assert store.rows[1].status == "active"
    assert store.rows[1].delivery_status == "pending"
    assert replacement.issued_link.token != failed_link.issued_link.token
    assert len([row for row in store.rows if row.status == "active"]) == 1
