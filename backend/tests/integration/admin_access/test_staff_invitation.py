"""T035 PostgreSQL evidence for a single owner-authorized staff invitation."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.account_security import SecurityNotificationDispatch
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.staff_invitation import (
    CreateStaffInvitation,
    DeliverStaffInvitation,
    ManageStaffInvitation,
    StaffInvitationError,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.persistence.staff_invitation_repository import (
    PostgresStaffInvitationStore,
)
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_cryptography_key_configuration,
    load_test_database_url,
)
from backend.app.web.admin_auth.security_notice_delivery import deliver_security_notices
from backend.app.web.admin_auth.staff_invitations import PostgresStaffInvitationOperations


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        _reset_admin_fixture_state(engine)
        yield engine
    finally:
        _reset_admin_fixture_state(engine)
        engine.dispose()


def _reset_admin_fixture_state(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE security_notification_deliveries, admin_accounts, owner_bootstrap_state "
                "RESTART IDENTITY CASCADE"
            )
        )
        connection.execute(
            text(
                "INSERT INTO owner_bootstrap_state (bootstrap_state_id, status) "
                "VALUES (1, 'open')"
            )
        )


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x91" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def _active_owner(engine: Engine) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO admin_accounts (role, status, password_hash) "
                "VALUES ('owner', 'active', '$argon2id$synthetic') "
                "RETURNING admin_account_id"
            )
        ).scalar_one()


def _email_protector() -> AdministrativeEmailProtector:
    return AdministrativeEmailProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator((b"\x92" * 12,)),
    )


def _invite(engine: Engine, *, owner_account_id: int, email: str, token: bytes):
    with engine.begin() as connection:
        key_ring = _key_ring()
        return CreateStaffInvitation(
            store=PostgresStaffInvitationStore(connection),
            email_protector=_email_protector(),
            link_lifecycle=SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator((token,)),
                protector=SecurityLinkProtector(key_ring=key_ring),
            ),
            audit=RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=FixedClock(NOW),
            ),
        ).invite(
            actor=AdministrativeActor(account_id=owner_account_id, role="owner"),
            email=email,
        )


def _resend(engine: Engine, *, owner_account_id: int, token: bytes):
    with engine.begin() as connection:
        key_ring = _key_ring()
        return ManageStaffInvitation(
            store=PostgresStaffInvitationStore(
                connection,
                email_protector=_email_protector(),
            ),
            link_lifecycle=SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator((token,)),
                protector=SecurityLinkProtector(key_ring=key_ring),
            ),
            audit=RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=FixedClock(NOW),
            ),
            clock=FixedClock(NOW),
        ).resend(actor=AdministrativeActor(account_id=owner_account_id, role="owner"))


def _cancel(engine: Engine, *, owner_account_id: int) -> None:
    with engine.begin() as connection:
        key_ring = _key_ring()
        ManageStaffInvitation(
            store=PostgresStaffInvitationStore(
                connection,
                email_protector=_email_protector(),
            ),
            link_lifecycle=SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator((b"\x98" * 32,)),
                protector=SecurityLinkProtector(key_ring=key_ring),
            ),
            audit=RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=FixedClock(NOW),
            ),
            clock=FixedClock(NOW),
        ).cancel(actor=AdministrativeActor(account_id=owner_account_id, role="owner"))


def _deliver_failure(engine: Engine, invitation) -> None:
    with engine.begin() as connection:
        DeliverStaffInvitation(
            delivery_state_store=PostgresSecurityLinkStore(connection),
            email_sender=EmailSimulator(outcome="failed"),
            audit=RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=FixedClock(NOW),
            ),
            clock=FixedClock(NOW),
        ).deliver(
            invitation=invitation,
            content="/admin/security-link#token=opaque-test-token",
        )


@pytest.mark.integration
def test_t035_owner_creates_exactly_one_pending_staff_without_access(
    migrated_engine: Engine,
) -> None:
    owner_id = _active_owner(migrated_engine)

    invitation = _invite(
        migrated_engine,
        owner_account_id=owner_id,
        email="  Synthetic.Staff@Example.TEST ",
        token=b"\x93" * 32,
    )

    with migrated_engine.connect() as connection:
        account = connection.execute(
            text(
                "SELECT role, status, password_hash FROM admin_accounts "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": invitation.account_id},
        ).one()
        claim = connection.execute(
            text(
                "SELECT claim_kind, lookup_digest, email_ciphertext, key_version "
                "FROM admin_email_claims WHERE admin_account_id = :account_id"
            ),
            {"account_id": invitation.account_id},
        ).one()
        link = connection.execute(
            text(
                "SELECT purpose, status, delivery_status, expires_at - issued_at "
                "FROM security_links WHERE admin_account_id = :account_id"
            ),
            {"account_id": invitation.account_id},
        ).one()
        access_counts = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM admin_sessions WHERE admin_account_id = :account_id), "
                "(SELECT count(*) FROM totp_factors WHERE admin_account_id = :account_id), "
                "(SELECT count(*) FROM recovery_codes WHERE admin_account_id = :account_id)"
            ),
            {"account_id": invitation.account_id},
        ).one()
        audit = connection.execute(
            text(
                "SELECT actor_account_id, action, result, target_reference "
                "FROM admin_audit_events"
            )
        ).one()

    assert account == ("staff", "pending", None)
    assert claim.claim_kind == "current"
    assert len(claim.lookup_digest) == 32
    assert b"synthetic.staff@example.test" not in claim.email_ciphertext
    assert claim.key_version == "v1"
    assert link == ("invitation", "active", "pending", timedelta(hours=24))
    assert access_counts == (0, 0, 0)
    assert audit == (
        owner_id,
        "staff_invitation",
        "succeeded",
        f"admin_account:{invitation.account_id}",
    )


class _InvitationNoticeSender:
    def __init__(self, first_notice_outcome: str = "accepted") -> None:
        self.notifications: list[OutboundNotification] = []
        self.first_notice_outcome = first_notice_outcome

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.notifications.append(notification)
        if len(self.notifications) == 1 and self.first_notice_outcome == "exception":
            raise RuntimeError("provider password=must-not-be-recorded")
        if len(self.notifications) == 1 and self.first_notice_outcome == "failed":
            return NotificationSendResult.failed(notification.channel)
        return NotificationSendResult.accepted(notification.channel)


def _owner_with_protected_email(engine: Engine) -> int:
    protector = AdministrativeEmailProtector(
        key_ring=CryptographyKeyRing(load_cryptography_key_configuration()),
        secret_generator=SequenceSecretGenerator((b"\x81" * 12,)),
    )
    protected = protector.protect("synthetic.owner@example.test")
    with engine.begin() as connection:
        owner_id = connection.execute(
            text(
                "INSERT INTO admin_accounts (role, status, password_hash) "
                "VALUES ('owner', 'active', '$argon2id$synthetic') "
                "RETURNING admin_account_id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO admin_email_claims "
                "(admin_account_id, claim_kind, lookup_digest, email_ciphertext, key_version) "
                "VALUES (:account_id, 'current', :lookup_digest, :ciphertext, :key_version)"
            ),
            {
                "account_id": owner_id,
                "lookup_digest": protected.lookup_digest,
                "ciphertext": protected.email_ciphertext,
                "key_version": protected.key_version,
            },
        )
    return owner_id


@pytest.mark.integration
@pytest.mark.parametrize("notice_outcome", ["accepted", "failed", "exception"])
def test_t096_invitation_notice_targets_only_owner_and_failure_does_not_undo_invitation(
    migrated_engine: Engine, notice_outcome: str
) -> None:
    owner_id = _owner_with_protected_email(migrated_engine)
    sender = _InvitationNoticeSender(first_notice_outcome=notice_outcome)

    outcome = PostgresStaffInvitationOperations(
        engine=migrated_engine, email_sender=sender
    ).invite(
        actor=AdministrativeActor(account_id=owner_id, role="owner"),
        email="synthetic.staff@example.test",
    )

    assert len(sender.notifications) == 2, [n.recipient for n in sender.notifications]
    owner_notice, staff_activation_link = sender.notifications
    assert owner_notice.recipient == "synthetic.owner@example.test"
    assert owner_notice.channel == EMAIL_CHANNEL
    assert "token" not in owner_notice.content.lower()
    assert "contraseña" not in owner_notice.content.lower()
    assert "código" not in owner_notice.content.lower()
    assert staff_activation_link.recipient == "synthetic.staff@example.test"
    assert "token=" in staff_activation_link.content
    with migrated_engine.connect() as connection:
        persisted = connection.execute(
            text(
                "SELECT event, template, status, sanitized_error "
                "FROM security_notification_deliveries WHERE event = 'staff_invited'"
            )
        ).one()
        invited_state = connection.execute(
            text(
                "SELECT a.status, l.status, l.delivery_status "
                "FROM admin_accounts a JOIN security_links l "
                "ON l.admin_account_id = a.admin_account_id WHERE a.role = 'staff'"
            )
        ).one()
    expected_status = "accepted" if notice_outcome == "accepted" else "failed"
    assert tuple(persisted) == (
        "staff_invited",
        "staff_invitation_notice",
        expected_status,
        None if expected_status == "accepted" else "security delivery failed.",
    )
    assert tuple(invited_state) == ("pending", "active", "accepted")

    # Replaying a dispatch for an already claimed/completed notice must not call the provider again.
    with migrated_engine.connect() as connection:
        delivery_id = connection.execute(
            text(
                "SELECT security_notification_delivery_id "
                "FROM security_notification_deliveries WHERE event = 'staff_invited'"
            )
        ).scalar_one()
    deliver_security_notices(
        engine=migrated_engine,
        email_sender=sender,
        notices=(
            SecurityNotificationDispatch(
                delivery_id=delivery_id,
                event="staff_invited",
                template="staff_invitation_notice",
                recipient="synthetic.owner@example.test",
            ),
        ),
    )
    assert len(sender.notifications) == 2


@pytest.mark.integration
def test_t035_rejects_existing_staff_or_claimed_email_without_new_account_or_link(
    migrated_engine: Engine,
) -> None:
    owner_id = _active_owner(migrated_engine)
    _invite(
        migrated_engine,
        owner_account_id=owner_id,
        email="synthetic.staff@example.test",
        token=b"\x94" * 32,
    )

    with pytest.raises(StaffInvitationError):
        _invite(
            migrated_engine,
            owner_account_id=owner_id,
            email="other.staff@example.test",
            token=b"\x95" * 32,
        )

    with migrated_engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM admin_accounts WHERE role = 'staff'), "
                "(SELECT count(*) FROM admin_email_claims WHERE admin_account_id <> :owner_id), "
                "(SELECT count(*) FROM security_links WHERE purpose = 'invitation'), "
                "(SELECT count(*) FROM admin_audit_events WHERE action = 'staff_invitation')"
            ),
            {"owner_id": owner_id},
        ).one()

    assert counts == (1, 1, 1, 1)


@pytest.mark.integration
def test_t040_two_concurrent_staff_invitations_allow_exactly_one_pending_account(
    migrated_engine: Engine,
) -> None:
    owner_id = _active_owner(migrated_engine)
    barrier = Barrier(2)

    def invite(email: str, token: bytes) -> str:
        barrier.wait(timeout=10)
        try:
            _invite(
                migrated_engine,
                owner_account_id=owner_id,
                email=email,
                token=token,
            )
        except StaffInvitationError:
            return "rejected"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda values: invite(*values),
                (
                    ("synthetic.first@example.test", b"\xd1" * 32),
                    ("synthetic.second@example.test", b"\xd2" * 32),
                ),
            )
        )

    with migrated_engine.connect() as connection:
        final_state = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM admin_accounts "
                " WHERE role = 'staff' AND status IN ('pending', 'active')), "
                "(SELECT count(*) FROM admin_email_claims), "
                "(SELECT count(*) FROM security_links WHERE purpose = 'invitation'), "
                "(SELECT count(*) FROM admin_audit_events "
                " WHERE action = 'staff_invitation'), "
                "(SELECT count(*) FROM admin_sessions), "
                "(SELECT count(*) FROM totp_factors), "
                "(SELECT count(*) FROM recovery_codes)"
            )
        ).one()

    assert sorted(outcomes) == ["accepted", "rejected"]
    assert tuple(final_state) == (1, 1, 1, 1, 0, 0, 0)


@pytest.mark.integration
def test_t036_failed_delivery_invalidates_the_link_but_preserves_pending_staff(
    migrated_engine: Engine,
) -> None:
    owner_id = _active_owner(migrated_engine)
    invitation = _invite(
        migrated_engine,
        owner_account_id=owner_id,
        email="synthetic.staff@example.test",
        token=b"\x96" * 32,
    )

    _deliver_failure(migrated_engine, invitation)

    with migrated_engine.connect() as connection:
        account = connection.execute(
            text(
                "SELECT role, status, password_hash FROM admin_accounts "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": invitation.account_id},
        ).one()
        link = connection.execute(
            text(
                "SELECT status, delivery_status, consumed_at, invalidated_at "
                "FROM security_links WHERE admin_account_id = :account_id"
            ),
            {"account_id": invitation.account_id},
        ).one()
        access_counts = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM admin_sessions WHERE admin_account_id = :account_id), "
                "(SELECT count(*) FROM totp_factors WHERE admin_account_id = :account_id), "
                "(SELECT count(*) FROM recovery_codes WHERE admin_account_id = :account_id)"
            ),
            {"account_id": invitation.account_id},
        ).one()
        audit_rows = connection.execute(
            text(
                "SELECT actor_account_id, action, result, target_reference "
                "FROM admin_audit_events ORDER BY admin_audit_event_id"
            )
        ).all()

    with migrated_engine.begin() as connection:
        failed_link = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(NOW),
            secret_generator=SequenceSecretGenerator((b"\x97" * 32,)),
            protector=SecurityLinkProtector(key_ring=_key_ring()),
        ).inspect(
            token=invitation.issued_link.token,
            purpose="invitation",
        )

    assert account == ("staff", "pending", None)
    assert link == ("invalidated", "failed", None, NOW)
    assert access_counts == (0, 0, 0)
    assert failed_link is None
    assert [tuple(row) for row in audit_rows] == [
        (owner_id, "staff_invitation", "succeeded", f"admin_account:{invitation.account_id}"),
        (owner_id, "staff_invitation", "failed", f"admin_account:{invitation.account_id}"),
    ]
    assert invitation.issued_link.token.hex() not in str(audit_rows)


@pytest.mark.integration
def test_t037_resend_invalidates_the_prior_link_and_starts_a_fresh_24_hour_window(
    migrated_engine: Engine,
) -> None:
    owner_id = _active_owner(migrated_engine)
    first = _invite(
        migrated_engine,
        owner_account_id=owner_id,
        email="synthetic.staff@example.test",
        token=b"\x99" * 32,
    )

    replacement = _resend(
        migrated_engine,
        owner_account_id=owner_id,
        token=b"\x9a" * 32,
    )
    with migrated_engine.begin() as connection:
        PostgresSecurityLinkStore(connection).mark_delivery_accepted(
            link_id=replacement.issued_link.stored_link.link_id,
            current_time=NOW,
        )

    with migrated_engine.connect() as connection:
        account = connection.execute(
            text(
                "SELECT status, password_hash FROM admin_accounts "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": first.account_id},
        ).one()
        links = connection.execute(
            text(
                "SELECT status, expires_at - issued_at FROM security_links "
                "WHERE admin_account_id = :account_id ORDER BY security_link_id"
            ),
            {"account_id": first.account_id},
        ).all()

    with migrated_engine.begin() as connection:
        lifecycle = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(NOW),
            secret_generator=SequenceSecretGenerator((b"\x9b" * 32,)),
            protector=SecurityLinkProtector(key_ring=_key_ring()),
        )
        prior_link = lifecycle.inspect(token=first.issued_link.token, purpose="invitation")
        current_link = lifecycle.inspect(
            token=replacement.issued_link.token,
            purpose="invitation",
        )

    assert replacement.account_id == first.account_id
    assert replacement.issued_link.token != first.issued_link.token
    assert account == ("pending", None)
    assert [tuple(row) for row in links] == [
        ("invalidated", timedelta(hours=24)),
        ("active", timedelta(hours=24)),
    ]
    assert prior_link is None
    assert current_link is not None


@pytest.mark.integration
def test_t037_cancel_invalidates_pending_state_and_releases_email_for_replacement(
    migrated_engine: Engine,
) -> None:
    owner_id = _active_owner(migrated_engine)
    cancelled = _invite(
        migrated_engine,
        owner_account_id=owner_id,
        email="synthetic.staff@example.test",
        token=b"\x9c" * 32,
    )

    _cancel(migrated_engine, owner_account_id=owner_id)
    replacement = _invite(
        migrated_engine,
        owner_account_id=owner_id,
        email="synthetic.staff@example.test",
        token=b"\x9d" * 32,
    )

    with migrated_engine.connect() as connection:
        cancelled_state = connection.execute(
            text(
                "SELECT status, password_hash FROM admin_accounts "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": cancelled.account_id},
        ).one()
        cancelled_claims = connection.execute(
            text(
                "SELECT count(*) FROM admin_email_claims "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": cancelled.account_id},
        ).scalar_one()
        cancelled_link = connection.execute(
            text(
                "SELECT status FROM security_links WHERE admin_account_id = :account_id"
            ),
            {"account_id": cancelled.account_id},
        ).scalar_one()
        pending_count = connection.execute(
            text(
                "SELECT count(*) FROM admin_accounts "
                "WHERE role = 'staff' AND status = 'pending'"
            )
        ).scalar_one()

    with migrated_engine.begin() as connection:
        cancelled_link_inspection = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(NOW),
            secret_generator=SequenceSecretGenerator((b"\x9e" * 32,)),
            protector=SecurityLinkProtector(key_ring=_key_ring()),
        ).inspect(
            token=cancelled.issued_link.token,
            purpose="invitation",
        )

    assert cancelled_state == ("deactivated", None)
    assert cancelled_claims == 0
    assert cancelled_link == "invalidated"
    assert cancelled_link_inspection is None
    assert replacement.account_id != cancelled.account_id
    assert pending_count == 1
