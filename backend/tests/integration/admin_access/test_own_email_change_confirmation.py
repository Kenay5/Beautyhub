"""T075 PostgreSQL evidence for one-use administrative email confirmation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch

import pyotp
import pytest
from sqlalchemy import Engine, delete, insert, select

from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import EMAIL_CHANNEL, NotificationSendResult
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAuditEvent,
    AdminEmailClaim,
    AdminSession,
    SecurityLink,
    SecurityNotificationDelivery,
)
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.persistence.own_email_change_confirmation_repository import (
    PostgresOwnEmailChangeConfirmationStore,
)
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.web.admin_auth.own_email_change_confirmation import (
    _PostgresOwnEmailChangeConfirmationOperation,
)
from backend.tests.integration.admin_access.test_admin_login_session import (
    EMAIL,
    NOW,
    PASSWORD,
    SECRET,
    _ring,
    _seed_account,
    migrated_engine,
)
from backend.tests.integration.admin_access.test_own_email_change_request import (
    _RecordingSender,
    _captured_token,
    _postgres_operation,
)


NEW_EMAIL = "synthetic.confirmed@example.test"


def _request(engine: Engine, *, new_email: str = NEW_EMAIL) -> bytes:
    # Delivery intents have no account FK, so the shared migrated fixture does not
    # remove them when it truncates accounts between integration cases.
    with engine.begin() as connection:
        connection.execute(delete(SecurityNotificationDelivery).where(
            SecurityNotificationDelivery.event == "email_changed"
        ))
    sender = _RecordingSender()
    assert _postgres_operation(engine, now=NOW, sender=sender).request(
        account_id=1,
        new_email=new_email,
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
    ) == "reserved"
    return _captured_token(sender)


def _confirmation(engine: Engine, sender: _RecordingSender, *, now=NOW):
    return _PostgresOwnEmailChangeConfirmationOperation(
        engine,
        email_sender=sender,
        clock=FixedClock(now),
        key_ring=_ring(),
    )


def _claim_digest(value: str) -> bytes:
    return AdministrativeEmailProtector(
        key_ring=_ring(), secret_generator=SystemSecretGenerator()
    ).lookup_digest(value)


@pytest.mark.integration
def test_t075_success_promotes_claim_consumes_link_closes_session_and_notifies_exactly_twice(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine, with_previous_session=True)
    token = _request(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(insert(SecurityLink).values(
            admin_account_id=1,
            purpose="password_recovery",
            token_digest=b"\x75" * 32,
            key_version="v1",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
            status="active",
            delivery_status="accepted",
        ))
    sender = _RecordingSender()
    operation = _confirmation(migrated_engine, sender)

    assert operation.confirm(token=token) == "completed"
    assert operation.confirm(token=token) == "unavailable"
    assert [notice.recipient for notice in sender.notifications] == [EMAIL, NEW_EMAIL]
    assert all("token" not in notice.content.lower() for notice in sender.notifications)

    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminEmailClaim.claim_kind, AdminEmailClaim.lookup_digest).where(
            AdminEmailClaim.admin_account_id == 1
        )).all() == [("current", _claim_digest(NEW_EMAIL))]
        assert connection.execute(select(SecurityLink.status).where(
            SecurityLink.admin_account_id == 1, SecurityLink.purpose == "email_change"
        )).scalar_one() == "consumed"
        assert connection.execute(select(SecurityLink.status).where(
            SecurityLink.admin_account_id == 1, SecurityLink.purpose == "password_recovery"
        )).scalar_one() == "invalidated"
        assert connection.execute(select(AdminSession.status).where(
            AdminSession.admin_account_id == 1
        )).scalars().all() == ["invalidated"]
        assert connection.execute(select(AdminAuditEvent.result).where(
            AdminAuditEvent.action == "email_change"
        ).order_by(AdminAuditEvent.admin_audit_event_id)).scalars().all() == ["succeeded", "succeeded"]
        assert connection.execute(select(
            SecurityNotificationDelivery.template, SecurityNotificationDelivery.status
        ).where(SecurityNotificationDelivery.event == "email_changed").order_by(
            SecurityNotificationDelivery.security_notification_delivery_id
        )).all() == [
            ("email_changed_previous_notice", "accepted"),
            ("email_changed_new_notice", "accepted"),
        ]


@pytest.mark.integration
def test_t075_lost_reservation_to_another_account_invalidates_link_without_changing_old_email(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine, with_previous_session=True)
    token = _request(migrated_engine)
    with migrated_engine.begin() as connection:
        reserved = connection.execute(select(
            AdminEmailClaim.lookup_digest,
            AdminEmailClaim.email_ciphertext,
            AdminEmailClaim.key_version,
        ).where(AdminEmailClaim.admin_account_id == 1, AdminEmailClaim.claim_kind == "reserved")).one()
        connection.execute(delete(AdminEmailClaim).where(
            AdminEmailClaim.admin_account_id == 1, AdminEmailClaim.claim_kind == "reserved"
        ))
        other_id = connection.execute(insert(AdminAccount).values(
            role="staff", status="pending"
        ).returning(AdminAccount.admin_account_id)).scalar_one()
        connection.execute(insert(AdminEmailClaim).values(
            admin_account_id=other_id,
            claim_kind="current",
            lookup_digest=reserved.lookup_digest,
            email_ciphertext=reserved.email_ciphertext,
            key_version=reserved.key_version,
        ))

    sender = _RecordingSender()
    assert _confirmation(migrated_engine, sender).confirm(token=token) == "unavailable"
    assert sender.notifications == []
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminEmailClaim.lookup_digest).where(
            AdminEmailClaim.admin_account_id == 1, AdminEmailClaim.claim_kind == "current"
        )).scalar_one() == _claim_digest(EMAIL)
        assert connection.execute(select(AdminEmailClaim.lookup_digest).where(
            AdminEmailClaim.admin_account_id == other_id, AdminEmailClaim.claim_kind == "current"
        )).scalar_one() == _claim_digest(NEW_EMAIL)
        assert connection.execute(select(SecurityLink.status).where(
            SecurityLink.admin_account_id == 1, SecurityLink.purpose == "email_change"
        )).scalar_one() == "invalidated"
        assert connection.execute(select(AdminSession.status).where(
            AdminSession.admin_account_id == 1
        )).scalars().all() == ["active"]


@pytest.mark.integration
def test_t075_confirmation_rechecks_uniqueness_after_a_competing_claim_commits(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine, with_previous_session=True)
    token = _request(migrated_engine)
    transfer_ready = Event()
    confirmation_located_link = Event()
    transfer_committed = Event()
    sender = _RecordingSender()

    def transfer_claim() -> None:
        with migrated_engine.begin() as connection:
            connection.execute(select(AdminAccount.admin_account_id).where(
                AdminAccount.admin_account_id == 1
            ).with_for_update()).scalar_one()
            reserved = connection.execute(select(
                AdminEmailClaim.lookup_digest,
                AdminEmailClaim.email_ciphertext,
                AdminEmailClaim.key_version,
            ).where(
                AdminEmailClaim.admin_account_id == 1,
                AdminEmailClaim.claim_kind == "reserved",
            )).one()
            connection.execute(delete(AdminEmailClaim).where(
                AdminEmailClaim.admin_account_id == 1,
                AdminEmailClaim.claim_kind == "reserved",
            ))
            other_id = connection.execute(insert(AdminAccount).values(
                role="staff", status="pending"
            ).returning(AdminAccount.admin_account_id)).scalar_one()
            connection.execute(insert(AdminEmailClaim).values(
                admin_account_id=other_id,
                claim_kind="current",
                lookup_digest=reserved.lookup_digest,
                email_ciphertext=reserved.email_ciphertext,
                key_version=reserved.key_version,
            ))
            transfer_ready.set()
            assert confirmation_located_link.wait(timeout=10)
        transfer_committed.set()

    original_lock = PostgresOwnEmailChangeConfirmationStore.lock_active_account

    def lock_after_transfer(self, *, account_id: int) -> bool:
        confirmation_located_link.set()
        assert transfer_committed.wait(timeout=10)
        return original_lock(self, account_id=account_id)

    def confirm() -> str:
        assert transfer_ready.wait(timeout=10)
        return _confirmation(migrated_engine, sender).confirm(token=token)

    with patch.object(PostgresOwnEmailChangeConfirmationStore, "lock_active_account", lock_after_transfer):
        with ThreadPoolExecutor(max_workers=2) as executor:
            transfer = executor.submit(transfer_claim)
            result = executor.submit(confirm)
            transfer.result()
            assert result.result() == "unavailable"

    assert sender.notifications == []
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminEmailClaim.lookup_digest).where(
            AdminEmailClaim.admin_account_id == 1,
            AdminEmailClaim.claim_kind == "current",
        )).scalar_one() == _claim_digest(EMAIL)
        assert connection.execute(select(SecurityLink.status).where(
            SecurityLink.admin_account_id == 1,
            SecurityLink.purpose == "email_change",
        )).scalar_one() == "invalidated"
        assert connection.execute(select(AdminSession.status).where(
            AdminSession.admin_account_id == 1,
        )).scalars().all() == ["active"]


@pytest.mark.integration
def test_t075_transaction_failure_rolls_back_claim_link_session_audit_and_notices(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine, with_previous_session=True)
    token = _request(migrated_engine)
    sender = _RecordingSender()
    operation = _confirmation(migrated_engine, sender)
    original_record = PostgresSecurityNotificationDeliveryStore.record_or_get
    calls = 0

    def fail_second_record(self, *, delivery):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic persistence failure")
        return original_record(self, delivery=delivery)

    with patch.object(PostgresSecurityNotificationDeliveryStore, "record_or_get", fail_second_record):
        with pytest.raises(RuntimeError, match="synthetic persistence failure"):
            operation.confirm(token=token)

    assert sender.notifications == []
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminEmailClaim.claim_kind, AdminEmailClaim.lookup_digest).where(
            AdminEmailClaim.admin_account_id == 1
        ).order_by(AdminEmailClaim.claim_kind)).all() == [
            ("current", _claim_digest(EMAIL)), ("reserved", _claim_digest(NEW_EMAIL))
        ]
        assert connection.execute(select(SecurityLink.status).where(
            SecurityLink.admin_account_id == 1, SecurityLink.purpose == "email_change"
        )).scalar_one() == "active"
        assert connection.execute(select(AdminSession.status).where(
            AdminSession.admin_account_id == 1
        )).scalars().all() == ["active"]
        assert connection.execute(select(AdminAuditEvent.result).where(
            AdminAuditEvent.action == "email_change"
        )).scalars().all() == ["succeeded"]
        assert connection.execute(select(SecurityNotificationDelivery.security_notification_delivery_id).where(
            SecurityNotificationDelivery.event == "email_changed"
        )).scalars().all() == []


@pytest.mark.integration
def test_t075_double_confirmation_has_one_winner_and_one_pair_of_notices(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    token = _request(migrated_engine)
    barrier = Barrier(2)
    sender = _RecordingSender()
    operation = _confirmation(migrated_engine, sender, now=NOW + timedelta(seconds=1))

    def confirm() -> str:
        barrier.wait()
        return operation.confirm(token=token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: confirm(), range(2)))
    assert sorted(outcomes) == ["completed", "unavailable"]
    assert sorted(notice.recipient for notice in sender.notifications) == sorted([EMAIL, NEW_EMAIL])
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminEmailClaim.lookup_digest).where(
            AdminEmailClaim.admin_account_id == 1, AdminEmailClaim.claim_kind == "current"
        )).scalar_one() == _claim_digest(NEW_EMAIL)
        assert len(connection.execute(select(SecurityNotificationDelivery.security_notification_delivery_id).where(
            SecurityNotificationDelivery.event == "email_changed"
        )).scalars().all()) == 2


@pytest.mark.integration
def test_t075_expired_link_releases_reservation_without_notices_or_session_change(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine, with_previous_session=True)
    token = _request(migrated_engine)
    sender = _RecordingSender()
    assert _confirmation(migrated_engine, sender, now=NOW + timedelta(minutes=30)).confirm(
        token=token
    ) == "unavailable"
    assert sender.notifications == []
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminEmailClaim.claim_kind, AdminEmailClaim.lookup_digest).where(
            AdminEmailClaim.admin_account_id == 1
        )).all() == [("current", _claim_digest(EMAIL))]
        assert connection.execute(select(SecurityLink.status).where(
            SecurityLink.admin_account_id == 1, SecurityLink.purpose == "email_change"
        )).scalar_one() == "expired"
        assert connection.execute(select(AdminSession.status).where(
            AdminSession.admin_account_id == 1
        )).scalars().all() == ["active"]


@pytest.mark.integration
def test_t075_notice_failure_preserves_change_and_still_attempts_both_recipients(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine, with_previous_session=True)
    token = _request(migrated_engine)

    class FirstNoticeFails(_RecordingSender):
        def send(self, notification):
            self.notifications.append(notification)
            if len(self.notifications) == 1:
                return NotificationSendResult.failed(EMAIL_CHANNEL)
            return NotificationSendResult.accepted(EMAIL_CHANNEL)

    sender = FirstNoticeFails()
    assert _confirmation(migrated_engine, sender).confirm(token=token) == "completed"
    assert [notice.recipient for notice in sender.notifications] == [EMAIL, NEW_EMAIL]
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminEmailClaim.lookup_digest).where(
            AdminEmailClaim.admin_account_id == 1, AdminEmailClaim.claim_kind == "current"
        )).scalar_one() == _claim_digest(NEW_EMAIL)
        assert connection.execute(select(SecurityNotificationDelivery.status).where(
            SecurityNotificationDelivery.event == "email_changed"
        ).order_by(SecurityNotificationDelivery.security_notification_delivery_id)).scalars().all() == [
            "failed", "accepted"
        ]
