"""T057 PostgreSQL evidence for atomic password replacement and rejection."""

from datetime import date, timedelta

import pyotp
import pytest
from sqlalchemy import Engine, func, select, text

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.change_password import ChangeAdministrativePassword
from backend.app.application.admin_access.security_change_invalidation import InvalidateAfterSecurityChange
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_account_security_repository import PostgresAdministrativeAccountSecurityStore
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import PostgresAdministrativeLockRecipientDirectory
from backend.app.infrastructure.persistence.admin_password_change_repository import PostgresAdministrativePasswordChangeStore
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminAuditEvent,
    AdminCredentialFailureEvent,
    AdminSession,
    SecurityNotificationDelivery,
    TotpPeriodUse,
)
from backend.app.infrastructure.persistence.security_change_invalidation_repository import PostgresSecurityChangeInvalidationStore
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.blocked_passwords import BlockedPasswordList
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.tests.integration.admin_access.test_admin_login_session import (
    NOW,
    PASSWORD,
    SECRET,
    _ring,
    _seed_account,
    migrated_engine,
)
from backend.app.web.admin_auth import change_password as password_change_web


def _operation(connection) -> ChangeAdministrativePassword:
    clock = FixedClock(NOW)
    entropy = SystemSecretGenerator()
    ring = _ring()
    security_store = PostgresAdministrativeAccountSecurityStore(connection)
    audit = RecordAdministrativeAuditEvent(
        store=PostgresAdministrativeAuditStore(connection), clock=clock
    )
    email_protector = AdministrativeEmailProtector(
        key_ring=ring, secret_generator=entropy
    )
    notices = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(
            key_ring=ring, secret_generator=entropy
        ),
    )
    return ChangeAdministrativePassword(
        store=PostgresAdministrativePasswordChangeStore(connection, email_protector),
        credential_guard=EnsureAdministrativeCredentialCheck(
            store=security_store, clock=clock
        ),
        failure_recorder=RecordProtectedAdministrativeCredentialFailure(
            failure_recorder=RecordAdministrativeCredentialFailure(
                store=security_store, clock=clock
            ),
            audit=audit,
            notifications=notices,
            recipients=PostgresAdministrativeLockRecipientDirectory(
                connection=connection, email_protector=email_protector
            ),
        ),
        password_hasher=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=ring, secret_generator=entropy
        ),
        totp=TotpAuthenticator(secret_generator=entropy),
        blocked_passwords=BlockedPasswordList(
            hashes=frozenset(), review_due=date(2035, 1, 1), clock=clock
        ),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection), clock=clock
        ),
        audit=audit,
        notifications=notices,
        clock=clock,
    )


@pytest.fixture()
def password_change_engine(migrated_engine: Engine) -> Engine:
    # Security-delivery intents are intentionally independent of account deletion.
    with migrated_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE security_notification_deliveries RESTART IDENTITY"))
    return migrated_engine


@pytest.mark.integration
def test_t057_success_atomically_replaces_password_and_closes_session(
    password_change_engine: Engine,
) -> None:
    migrated_engine = password_change_engine
    _seed_account(migrated_engine, with_previous_session=True)
    protected_reservation = AdministrativeEmailProtector(
        key_ring=_ring(), secret_generator=SystemSecretGenerator()
    ).protect("synthetic.reserved@example.test")
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO admin_email_claims "
                "(admin_account_id, claim_kind, lookup_digest, email_ciphertext, key_version) "
                "VALUES (1, 'reserved', :digest, :ciphertext, 'v1')"
            ),
            {
                "digest": protected_reservation.lookup_digest,
                "ciphertext": protected_reservation.email_ciphertext,
            },
        )
        connection.execute(
            text(
                "INSERT INTO security_links "
                "(admin_account_id, purpose, token_digest, key_version, issued_at, expires_at, "
                "status, delivery_status) "
                "VALUES (1, 'email_change', :digest, 'v1', :issued_at, :expires_at, "
                "'active', 'accepted')"
            ),
            {
                "digest": b"\x99" * 32,
                "issued_at": NOW,
                "expires_at": NOW + timedelta(minutes=30),
            },
        )
        connection.execute(
            text(
                "INSERT INTO pending_security_setups "
                "(admin_account_id, flow, status, totp_secret_ciphertext, "
                "key_version, created_at, expires_at) "
                "VALUES (1, 'totp_replacement', 'pending', :ciphertext, 'v1', "
                ":created_at, :expires_at)"
            ),
            {
                "ciphertext": b"synthetic pending ciphertext",
                "created_at": NOW,
                "expires_at": NOW + timedelta(minutes=30),
            },
        )
    with migrated_engine.connect() as connection:
        previous_notices = connection.execute(
            select(func.count()).select_from(SecurityNotificationDelivery)
        ).scalar_one()
    code = pyotp.TOTP(SECRET.decode("ascii")).at(NOW)
    new_password = "fresh synthetic phrase"

    with migrated_engine.begin() as connection:
        result = _operation(connection).change(
            account_id=1,
            current_password=PASSWORD,
            totp_code=code,
            new_password=new_password,
        )
    assert result.status == "changed"

    with migrated_engine.connect() as connection:
        password_hash = connection.execute(
            select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == 1)
        ).scalar_one()
        sessions = connection.execute(
            select(AdminSession.status).where(AdminSession.admin_account_id == 1)
        ).scalars().all()
        assert sessions == ["invalidated"]
        assert connection.execute(text("SELECT status FROM security_links")).scalar_one() == "invalidated"
        assert connection.execute(text("SELECT status FROM pending_security_setups")).scalar_one() == "invalidated"
        assert connection.execute(text("SELECT claim_kind FROM admin_email_claims ORDER BY claim_kind")).scalars().all() == ["current"]
        assert connection.execute(select(func.count()).select_from(TotpPeriodUse)).scalar_one() == 1
        assert connection.execute(select(AdminAuditEvent.action, AdminAuditEvent.result)).all() == [
            ("password_change", "succeeded")
        ]
        assert connection.execute(
            select(func.count()).select_from(SecurityNotificationDelivery)
        ).scalar_one() == previous_notices + 1
        assert connection.execute(
            select(SecurityNotificationDelivery.event, SecurityNotificationDelivery.status)
            .order_by(SecurityNotificationDelivery.security_notification_delivery_id.desc())
            .limit(1)
        ).one() == ("password_changed", "pending")
    hasher = AdministrativePasswordHasher()
    assert not hasher.verify_and_upgrade(stored_hash=password_hash, password=PASSWORD).verified
    assert hasher.verify_and_upgrade(stored_hash=password_hash, password=new_password).verified


@pytest.mark.integration
def test_t057_rejected_credentials_keep_password_session_and_totp_unused(
    password_change_engine: Engine,
) -> None:
    migrated_engine = password_change_engine
    _seed_account(migrated_engine, with_previous_session=True)
    with migrated_engine.connect() as connection:
        previous_notices = connection.execute(
            select(func.count()).select_from(SecurityNotificationDelivery)
        ).scalar_one()
    code = pyotp.TOTP(SECRET.decode("ascii")).at(NOW)

    with migrated_engine.begin() as connection:
        result = _operation(connection).change(
            account_id=1,
            current_password="wrong synthetic phrase",
            totp_code=code,
            new_password="fresh synthetic phrase",
        )
    assert result.status == "invalid_credentials"

    with migrated_engine.connect() as connection:
        password_hash = connection.execute(
            select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == 1)
        ).scalar_one()
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        assert connection.execute(select(func.count()).select_from(TotpPeriodUse)).scalar_one() == 0
        assert connection.execute(select(func.count()).select_from(AdminCredentialFailureEvent)).scalar_one() == 1
        assert connection.execute(select(func.count()).select_from(SecurityNotificationDelivery)).scalar_one() == previous_notices
        assert connection.execute(select(AdminAuditEvent.action, AdminAuditEvent.result)).all() == [
            ("password_change", "failed")
        ]
    assert AdministrativePasswordHasher().verify_and_upgrade(
        stored_hash=password_hash, password=PASSWORD
    ).verified


@pytest.mark.integration
def test_t057_fifth_shared_credential_failure_locks_without_closing_existing_session(
    password_change_engine: Engine,
) -> None:
    _seed_account(password_change_engine, with_previous_session=True)
    with password_change_engine.begin() as connection:
        recorder = RecordAdministrativeCredentialFailure(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(NOW),
        )
        for _ in range(4):
            recorder.record(account_id=1, operation="login")

    with password_change_engine.begin() as connection:
        result = _operation(connection).change(
            account_id=1,
            current_password="wrong synthetic phrase",
            totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
            new_password="fresh synthetic phrase",
        )
    assert result.status == "invalid_credentials"

    with password_change_engine.connect() as connection:
        assert connection.execute(
            select(AdminAccountSecurityState.lock_until).where(
                AdminAccountSecurityState.admin_account_id == 1
            )
        ).scalar_one() == NOW + timedelta(minutes=15)
        assert connection.execute(select(func.count()).select_from(AdminCredentialFailureEvent)).scalar_one() == 5
        assert connection.execute(select(AdminSession.status)).scalar_one() == "active"
        assert connection.execute(select(func.count()).select_from(TotpPeriodUse)).scalar_one() == 0
        assert connection.execute(
            select(SecurityNotificationDelivery.event)
        ).scalars().all() == ["account_locked"]


@pytest.mark.integration
@pytest.mark.parametrize("delivery_outcome", ["accepted", "failed"])
def test_t057_notice_attempt_follows_commit_and_cannot_undo_the_change(
    password_change_engine: Engine, monkeypatch, delivery_outcome: str
) -> None:
    _seed_account(password_change_engine, with_previous_session=True)
    sender = EmailSimulator(outcome=delivery_outcome)
    monkeypatch.setattr(password_change_web, "_compose_change_password", _operation)
    code = pyotp.TOTP(SECRET.decode("ascii")).at(NOW)

    result = password_change_web._PostgresPasswordChangeOperation(
        password_change_engine, email_sender=sender
    ).change(
        account_id=1,
        current_password=PASSWORD,
        totp_code=code,
        new_password="fresh synthetic phrase",
    )

    assert result == "changed"
    assert len(sender.notifications) == 1
    assert sender.notifications[0].recipient == "synthetic.owner@example.test"
    assert PASSWORD not in sender.notifications[0].content
    assert code not in sender.notifications[0].content
    with password_change_engine.connect() as connection:
        assert connection.execute(select(AdminSession.status)).scalar_one() == "invalidated"
        notice = connection.execute(
            select(
                SecurityNotificationDelivery.status,
                SecurityNotificationDelivery.sanitized_error,
                SecurityNotificationDelivery.recipient_ciphertext,
            )
        ).one()
        assert notice.status == delivery_outcome
        if delivery_outcome == "failed":
            assert notice.sanitized_error == "security delivery failed."
        else:
            assert notice.sanitized_error is None
            assert notice.recipient_ciphertext is None
