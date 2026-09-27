"""PostgreSQL verification of T080 atomic deactivation and replacement."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete, func, insert, select, text, update

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.admin_access.staff_deactivation import DeactivateStaff
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.models import (
    AdminAccount, AdminEmailClaim, AdminSession, DeactivatedStaffIdentity, PendingSecuritySetup, RecoveryCode,
    SecurityLink, TotpFactor, SecurityNotificationDelivery,
)
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.persistence.staff_deactivation_repository import PostgresStaffDeactivationStore
from backend.app.web.admin_auth.staff_deactivation import PostgresStaffDeactivationOperations
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import load_cryptography_key_configuration
from backend.tests.integration.admin_access.test_admin_login_session import (
    NOW, _ring, _seed_account, migrated_engine,
)
from backend.tests.integration.admin_access.test_staff_invitation import _invite


def _seed_active_staff(engine, owner_id: int) -> int:
    invite = _invite(
        engine,
        owner_account_id=owner_id,
        email="synthetic.staff@example.test",
        token=b"\x61" * 32,
    )
    email = AdministrativeEmailProtector(
        key_ring=_ring(), secret_generator=SequenceSecretGenerator((b"\x62" * 12,))
    ).protect("synthetic.staff@example.test")
    with engine.begin() as connection:
        connection.execute(
            update(AdminAccount).where(AdminAccount.admin_account_id == invite.account_id)
            .values(status="active", password_hash="$argon2id$synthetic-staff")
        )
        connection.execute(
            update(AdminEmailClaim).where(AdminEmailClaim.admin_account_id == invite.account_id)
            .values(lookup_digest=email.lookup_digest, email_ciphertext=email.email_ciphertext,
                    key_version=email.key_version)
        )
        factor_id = connection.execute(
            insert(TotpFactor).values(
                admin_account_id=invite.account_id, totp_secret_ciphertext=b"encrypted-totp",
                key_version="v1", algorithm="SHA1", digits=6, period_seconds=30,
                status="active", confirmed_at=NOW,
            ).returning(TotpFactor.totp_factor_id)
        ).scalar_one()
        connection.execute(insert(RecoveryCode), [
            {"admin_account_id": invite.account_id, "lookup_digest": b"\x63" * 32,
             "key_version": "v1", "position": 1, "status": "active"},
            {"admin_account_id": invite.account_id, "lookup_digest": b"\x64" * 32,
             "key_version": "v1", "position": 2, "status": "active"},
        ])
        connection.execute(
            insert(AdminSession).values(
                admin_account_id=invite.account_id, session_digest=b"\x65" * 32,
                csrf_digest=b"\x66" * 32, key_version="v1", created_at=NOW,
                last_human_activity_at=NOW, absolute_expires_at=NOW + timedelta(hours=8),
                status="active",
            )
        )
        for purpose in ("password_recovery", "forced_password_reset", "email_change", "totp_replacement"):
            connection.execute(insert(SecurityLink).values(
                admin_account_id=invite.account_id, purpose=purpose,
                token_digest=bytes([len(purpose)]) * 32, key_version="v1",
                issued_at=NOW, expires_at=NOW + timedelta(minutes=30), status="active",
                delivery_status="accepted",
            ))
        connection.execute(insert(PendingSecuritySetup).values(
            admin_account_id=invite.account_id, flow="staff_activation", status="pending",
            totp_secret_ciphertext=b"pending-secret", key_version="v1",
            created_at=NOW, expires_at=NOW + timedelta(minutes=30),
        ))
        connection.execute(insert(PendingSecuritySetup).values(
            admin_account_id=invite.account_id, flow="totp_replacement", status="pending",
            totp_secret_ciphertext=b"pending-secret-2", key_version="v1",
            verified_recovery_code_digest=b"\x67" * 32,
            created_at=NOW, expires_at=NOW + timedelta(minutes=30),
        ))
    return invite.account_id


def _operation(connection, *, fail_audit=False):
    class AuditFailure:
        def record(self, **kwargs):
            if fail_audit:
                raise RuntimeError("injected audit failure")
            RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection), clock=FixedClock(NOW)
            ).record(**kwargs)

    entropy = SequenceSecretGenerator((b"\x68" * 12, b"\x69" * 12))
    key_ring = _ring()
    return DeactivateStaff(
        store=PostgresStaffDeactivationStore(
            connection,
            email_protector=AdministrativeEmailProtector(key_ring=key_ring, secret_generator=entropy),
        ),
        audit=AuditFailure(),
        notifications=RecordSecurityNotificationDelivery(
            store=PostgresSecurityNotificationDeliveryStore(connection),
            protector=SecurityNotificationDeliveryProtector(key_ring=key_ring, secret_generator=entropy),
        ),
        clock=FixedClock(NOW),
    )


@pytest.mark.integration
def test_t080_deactivation_atomically_revokes_every_credential_and_allows_new_invitation(migrated_engine):
    _seed_account(migrated_engine)
    owner_id = 1
    staff_id = _seed_active_staff(migrated_engine, owner_id)
    actor = AdministrativeActor(account_id=owner_id, role="owner")

    with migrated_engine.begin() as connection:
        result = _operation(connection).deactivate(actor=actor)
    assert result.account_id == staff_id

    with migrated_engine.connect() as connection:
        account = connection.execute(select(AdminAccount.status, AdminAccount.password_hash).where(
            AdminAccount.admin_account_id == staff_id)).one()
        assert account == ("deactivated", None)
        assert connection.execute(select(AdminEmailClaim.admin_account_id).where(
            AdminEmailClaim.admin_account_id == staff_id)).all() == []
        retained_identity = connection.execute(select(
            DeactivatedStaffIdentity.key_version, DeactivatedStaffIdentity.identifiable_until
        ).where(DeactivatedStaffIdentity.admin_account_id == staff_id)).one()
        assert retained_identity.key_version == "v1"
        assert retained_identity.identifiable_until == NOW.replace(year=NOW.year + 1)
        assert connection.execute(select(AdminSession.status).where(
            AdminSession.admin_account_id == staff_id)).scalars().all() == ["invalidated"]
        assert set(connection.execute(select(SecurityLink.status).where(
            SecurityLink.admin_account_id == staff_id)).scalars()) == {"invalidated"}
        assert set(connection.execute(select(PendingSecuritySetup.status,
            PendingSecuritySetup.totp_secret_ciphertext,
            PendingSecuritySetup.verified_recovery_code_digest).where(
            PendingSecuritySetup.admin_account_id == staff_id)).all()) == {
                ("invalidated", None, None), ("invalidated", None, None)}
        factor = connection.execute(select(TotpFactor.status, TotpFactor.totp_secret_ciphertext,
            TotpFactor.key_version).where(TotpFactor.admin_account_id == staff_id)).one()
        assert factor == ("invalidated", None, None)
        assert connection.execute(select(func.count()).select_from(RecoveryCode).where(
            RecoveryCode.admin_account_id == staff_id)).scalar_one() == 0
        assert connection.execute(select(SecurityNotificationDelivery.status).where(
            SecurityNotificationDelivery.security_notification_delivery_id == result.notification_delivery_id
        )).scalar_one() == "pending"
        audit = connection.execute(text("SELECT actor_account_id, action, result, target_reference FROM admin_audit_events WHERE target_reference = :target AND action = 'staff_deactivation'"),
            {"target": f"admin_account:{staff_id}"}).one()
        assert audit == (owner_id, "staff_deactivation", "succeeded", f"admin_account:{staff_id}")

    replacement = _invite(migrated_engine, owner_account_id=owner_id,
        email="synthetic.staff@example.test", token=b"\x6a" * 32)
    assert replacement.account_id != staff_id
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminAccount.status).where(
            AdminAccount.admin_account_id == staff_id)).scalar_one() == "deactivated"


@pytest.mark.integration
def test_t080_audit_failure_rolls_back_deactivation_credentials_sessions_and_links(migrated_engine):
    _seed_account(migrated_engine)
    staff_id = _seed_active_staff(migrated_engine, 1)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        with migrated_engine.begin() as connection:
            _operation(connection, fail_audit=True).deactivate(
                actor=AdministrativeActor(account_id=1, role="owner")
            )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminAccount.status, AdminAccount.password_hash).where(
            AdminAccount.admin_account_id == staff_id)).one() == ("active", "$argon2id$synthetic-staff")
        assert connection.execute(select(DeactivatedStaffIdentity.admin_account_id).where(
            DeactivatedStaffIdentity.admin_account_id == staff_id)).first() is None
        assert connection.execute(select(AdminSession.status).where(
            AdminSession.admin_account_id == staff_id)).scalar_one() == "active"
        assert connection.execute(select(func.count()).select_from(AdminEmailClaim).where(
            AdminEmailClaim.admin_account_id == staff_id)).scalar_one() == 1
        assert connection.execute(select(func.count()).select_from(SecurityLink).where(
            SecurityLink.admin_account_id == staff_id, SecurityLink.status == "active")).scalar_one() == 5
        assert connection.execute(select(TotpFactor.status).where(
            TotpFactor.admin_account_id == staff_id)).scalar_one() == "active"
        assert connection.execute(select(func.count()).select_from(RecoveryCode).where(
            RecoveryCode.admin_account_id == staff_id, RecoveryCode.status == "active")).scalar_one() == 2
        assert connection.execute(select(func.count()).select_from(PendingSecuritySetup).where(
            PendingSecuritySetup.admin_account_id == staff_id,
            PendingSecuritySetup.status == "pending",
            PendingSecuritySetup.totp_secret_ciphertext.is_not(None),
        )).scalar_one() == 2
        assert connection.execute(select(DeactivatedStaffIdentity.admin_account_id).where(
            DeactivatedStaffIdentity.admin_account_id == staff_id)).first() is None


@pytest.mark.integration
def test_t080_owner_notice_delivery_failure_does_not_undo_deactivation(migrated_engine):
    # Delivery intents are intentionally not cascaded with account identity; the
    # imported shared fixture resets accounts, so isolate its external idempotency rows.
    with migrated_engine.begin() as connection:
        connection.execute(delete(SecurityNotificationDelivery))
    _seed_account(migrated_engine)
    staff_id = _seed_active_staff(migrated_engine, 1)
    sender = EmailSimulator(outcome="failed")
    runtime_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    protected_owner_email = AdministrativeEmailProtector(
        key_ring=runtime_ring, secret_generator=SystemSecretGenerator()
    ).protect("synthetic.owner@example.test")
    with migrated_engine.begin() as connection:
        connection.execute(update(AdminEmailClaim).where(
            AdminEmailClaim.admin_account_id == 1).values(
                lookup_digest=protected_owner_email.lookup_digest,
                email_ciphertext=protected_owner_email.email_ciphertext,
                key_version=protected_owner_email.key_version,
            ))

    PostgresStaffDeactivationOperations(
        engine=migrated_engine, email_sender=sender
    ).deactivate(actor=AdministrativeActor(account_id=1, role="owner"))

    assert len(sender.notifications) == 1
    assert sender.notifications[0].recipient == "synthetic.owner@example.test"
    assert "enlace" not in sender.notifications[0].content.lower()
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminAccount.status).where(
            AdminAccount.admin_account_id == staff_id)).scalar_one() == "deactivated"
        assert connection.execute(select(SecurityNotificationDelivery.status).where(
            SecurityNotificationDelivery.event == "staff_deactivated")).scalar_one() == "failed"
