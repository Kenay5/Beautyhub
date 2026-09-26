"""T062 owner-forced staff reset journey against PostgreSQL."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, update

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.account_security import CheckPostRecoveryFactorReplacement
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import EMAIL_CHANNEL, NotificationSendResult, OutboundNotification
from backend.app.infrastructure.persistence.admin_login_repository import PostgresAdministrativeLoginStore
from backend.app.infrastructure.persistence.models import AdminAccount, AdminAccountSecurityState, AdminAuditEvent, AdminEmailClaim, AdminSession, RecoveryCode, SecurityLink, TotpFactor
from backend.app.infrastructure.persistence.admin_account_security_repository import PostgresAdministrativeAccountSecurityStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration
from backend.app.web.admin_auth.forced_staff_password_reset import (
    PostgresForcedPasswordResetOperations,
    get_forced_password_reset_operations,
    router as forced_reset_router,
)
from backend.app.web.admin_auth.lost_factor_replacement_request import (
    PostgresLostFactorReplacementRequestOperations,
    get_lost_factor_replacement_request_operations,
    router as lost_factor_router,
)
from backend.app.web.admin_auth.password_recovery_completion import (
    _PostgresPasswordRecoveryCompletionOperation,
    get_password_recovery_completion_operations,
    router as completion_router,
)
from backend.app.web.admin_auth.mutation_protection import require_administrative_mutation_protection
from backend.app.web.admin_auth.security_link_transport import decode_security_link_token
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.app.web.admin_security_headers import register_administrative_security_headers
from backend.tests.integration.admin_access.test_admin_login_session import migrated_engine


OWNER_EMAIL = "synthetic.owner@example.test"
STAFF_EMAIL = "synthetic.staff@example.test"
OLD_PASSWORD = "synthetic staff previous password"
NEW_PASSWORD = "synthetic staff replacement password"


class RecordingSender:
    def __init__(self, *, outcome: str = "accepted") -> None:
        self.notifications: list[OutboundNotification] = []
        self.outcome = outcome

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.notifications.append(notification)
        if self.outcome == "raise":
            raise RuntimeError("synthetic provider failure")
        if self.outcome == "failed":
            return NotificationSendResult.failed(notification.channel)
        return NotificationSendResult.accepted(notification.channel)


def _seed(engine: Engine) -> tuple[int, int]:
    ring = CryptographyKeyRing(load_cryptography_key_configuration())
    entropy = SystemSecretGenerator()
    protector = AdministrativeEmailProtector(key_ring=ring, secret_generator=entropy)
    owner_email = protector.protect(OWNER_EMAIL)
    staff_email = protector.protect(STAFF_EMAIL)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        owner_id = connection.execute(insert(AdminAccount).values(
            role="owner", status="active", password_hash=AdministrativePasswordHasher().hash_password("synthetic owner password phrase"),
        ).returning(AdminAccount.admin_account_id)).scalar_one()
        staff_id = connection.execute(insert(AdminAccount).values(
            role="staff", status="active", password_hash=AdministrativePasswordHasher().hash_password(OLD_PASSWORD),
        ).returning(AdminAccount.admin_account_id)).scalar_one()
        for account_id, email in ((owner_id, owner_email), (staff_id, staff_email)):
            connection.execute(insert(AdminEmailClaim).values(
                admin_account_id=account_id, claim_kind="current", lookup_digest=email.lookup_digest,
                email_ciphertext=email.email_ciphertext, key_version=email.key_version,
            ))
        for account_id, marker in ((owner_id, 0x51), (staff_id, 0x61)):
            connection.execute(insert(AdminSession).values(
                admin_account_id=account_id, session_digest=bytes([marker]) * 32,
                csrf_digest=bytes([marker + 1]) * 32, key_version=ring.key_version,
                created_at=now, last_human_activity_at=now,
                absolute_expires_at=now + timedelta(hours=8), status="active",
            ))
    return owner_id, staff_id


def _client(engine: Engine, *, sender: RecordingSender, actor: AdministrativeActor) -> TestClient:
    app = FastAPI()
    app.include_router(forced_reset_router)
    app.include_router(completion_router)
    app.include_router(lost_factor_router)
    register_administrative_security_headers(app)
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: actor
    app.dependency_overrides[require_administrative_mutation_protection] = lambda: None
    app.dependency_overrides[get_forced_password_reset_operations] = lambda: PostgresForcedPasswordResetOperations(engine=engine, email_sender=sender)
    app.dependency_overrides[get_password_recovery_completion_operations] = lambda: _PostgresPasswordRecoveryCompletionOperation(engine=engine, email_sender=sender)
    app.dependency_overrides[get_lost_factor_replacement_request_operations] = lambda: PostgresLostFactorReplacementRequestOperations(engine=engine, email_sender=sender)
    return TestClient(app, client=("127.0.0.1", 50000))


def _request_reset(client: TestClient) -> dict:
    response = client.post("/api/admin/staff-password-reset")
    assert response.status_code == 200
    return response.json()


def _token(sender: RecordingSender, index: int) -> str:
    match = re.search(r"#token=([A-Za-z0-9_-]{43})", sender.notifications[index].content)
    assert match is not None
    return match.group(1)


@pytest.mark.integration
def test_t062_owner_forces_staff_password_reset_and_staff_completes_email_link(migrated_engine: Engine) -> None:
    owner_id, staff_id = _seed(migrated_engine)
    sender = RecordingSender()
    with _client(migrated_engine, sender=sender, actor=AdministrativeActor(owner_id, "owner")) as client:
        response = client.post(
            "/api/admin/staff-password-reset",
            json={"newPassword": "the owner cannot choose this password"},
        )
        assert response.status_code == 200
        assert response.json() == {"deliveryStatus": "accepted", "detail": None}
        assert "set-cookie" not in response.headers
        assert STAFF_EMAIL not in response.text
        assert "token" not in response.text.lower()
        assert "password" not in response.text.lower()

        link_content = sender.notifications[0].content
        assert sender.notifications[0].recipient == STAFF_EMAIL
        assert sender.notifications[0].channel == EMAIL_CHANNEL
        assert "/admin/password-recovery" in link_content
        match = re.search(r"#token=([A-Za-z0-9_-]{43})", link_content)
        assert match is not None
        token_text = match.group(1)
        token = decode_security_link_token(token_text)

        with migrated_engine.connect() as connection:
            staff_account = connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == staff_id)).scalar_one()
            sessions = connection.execute(select(AdminSession.admin_account_id, AdminSession.status).order_by(AdminSession.admin_session_id)).all()
            link = connection.execute(select(SecurityLink.purpose, SecurityLink.status, SecurityLink.delivery_status, SecurityLink.expires_at, SecurityLink.issued_at).where(SecurityLink.admin_account_id == staff_id)).one()
        assert staff_account is None
        assert sessions == [(owner_id, "active"), (staff_id, "invalidated")]
        assert link.purpose == "forced_password_reset"
        assert (link.status, link.delivery_status) == ("active", "accepted")
        assert timedelta(minutes=29, seconds=59) < link.expires_at - link.issued_at <= timedelta(minutes=30)
        assert token_text not in repr(link)

        with migrated_engine.connect() as connection:
            email_lookup = AdministrativeEmailProtector(key_ring=CryptographyKeyRing(load_cryptography_key_configuration()), secret_generator=SystemSecretGenerator())
            candidate = PostgresAdministrativeLoginStore(connection).load_candidate(
                email_lookup_digest=email_lookup.protect(STAFF_EMAIL).lookup_digest
            )
        assert candidate is None

        completion = client.post(
            "/api/admin/password-recovery/complete",
            json={"token": token_text, "newPassword": NEW_PASSWORD},
        )
        assert completion.status_code == 204
        assert completion.content == b""
        assert "set-cookie" not in completion.headers

        notifications_before_lost_factor_request = len(sender.notifications)
        lost_factor = client.post(
            "/api/admin/totp-replacement/request",
            json={"email": STAFF_EMAIL, "password": NEW_PASSWORD},
        )
        assert lost_factor.status_code == 202
        assert lost_factor.json() == {
            "message": "Si la cuenta puede iniciar el reemplazo del segundo factor, recibirás instrucciones en el correo registrado."
        }
        assert len(sender.notifications) == notifications_before_lost_factor_request

    with migrated_engine.connect() as connection:
        password_hash = connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == staff_id)).scalar_one()
        assert connection.execute(select(SecurityLink.status).where(SecurityLink.admin_account_id == staff_id)).scalar_one() == "consumed"
        assert connection.execute(select(AdminSession.status).where(AdminSession.admin_account_id == staff_id)).scalars().all() == ["invalidated"]
        assert connection.execute(select(AdminAccountSecurityState.post_recovery_second_factor_restricted).where(AdminAccountSecurityState.admin_account_id == staff_id)).scalar_one()
        assert connection.execute(select(TotpFactor.totp_factor_id).where(TotpFactor.admin_account_id == staff_id)).all() == []
        assert connection.execute(select(RecoveryCode.recovery_code_id).where(RecoveryCode.admin_account_id == staff_id)).all() == []
        assert connection.execute(select(SecurityLink.security_link_id).where(
            SecurityLink.admin_account_id == staff_id,
            SecurityLink.purpose == "totp_replacement",
        )).all() == []
        assert not CheckPostRecoveryFactorReplacement(
            store=PostgresAdministrativeAccountSecurityStore(connection)
        ).is_allowed(account_id=staff_id)
        assert connection.execute(select(AdminAuditEvent.action, AdminAuditEvent.actor_account_id, AdminAuditEvent.target_reference).where(AdminAuditEvent.target_reference == f"admin_account:{staff_id}")).one() == ("password_recovery", owner_id, f"admin_account:{staff_id}")
    assert AdministrativePasswordHasher().verify_and_upgrade(stored_hash=password_hash, password=NEW_PASSWORD).verified
    assert not AdministrativePasswordHasher().verify_and_upgrade(stored_hash=password_hash, password=OLD_PASSWORD).verified


@pytest.mark.integration
def test_t062_staff_actor_cannot_force_password_reset(migrated_engine: Engine) -> None:
    _owner_id, staff_id = _seed(migrated_engine)
    sender = RecordingSender()
    with _client(migrated_engine, sender=sender, actor=AdministrativeActor(staff_id, "staff")) as client:
        response = client.post("/api/admin/staff-password-reset")
    assert response.status_code == 403
    assert response.json() == {"detail": "No tienes permiso para realizar esta operación."}
    assert sender.notifications == []
    with migrated_engine.connect() as connection:
        assert connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == staff_id)).scalar_one() is not None
        assert connection.execute(select(AdminSession.status).where(AdminSession.admin_account_id == staff_id)).scalar_one() == "active"
        assert connection.execute(select(SecurityLink.security_link_id).where(SecurityLink.purpose == "forced_password_reset")).all() == []


@pytest.mark.integration
@pytest.mark.parametrize("outcome", ["failed", "raise"])
def test_t063_failed_delivery_retires_only_link_and_owner_can_issue_full_lifetime_replacement(
    migrated_engine: Engine, outcome: str
) -> None:
    owner_id, staff_id = _seed(migrated_engine)
    sender = RecordingSender(outcome=outcome)
    with _client(migrated_engine, sender=sender, actor=AdministrativeActor(owner_id, "owner")) as client:
        failed = _request_reset(client)
        assert failed["deliveryStatus"] == "failed"
        old_token = _token(sender, 0)
        with migrated_engine.connect() as connection:
            old_link = connection.execute(select(SecurityLink.status, SecurityLink.delivery_status).where(SecurityLink.admin_account_id == staff_id)).one()
            assert (old_link.status, old_link.delivery_status) == ("invalidated", "failed")
            assert connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == staff_id)).scalar_one() is None
            assert connection.execute(select(AdminSession.status).where(AdminSession.admin_account_id == staff_id)).scalar_one() == "invalidated"
            audit = connection.execute(select(AdminAuditEvent.action, AdminAuditEvent.result, AdminAuditEvent.actor_account_id).where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}"
            ).order_by(AdminAuditEvent.admin_audit_event_id.desc())).first()
            assert audit == ("password_recovery", "failed", owner_id)
            email_lookup = AdministrativeEmailProtector(
                key_ring=CryptographyKeyRing(load_cryptography_key_configuration()),
                secret_generator=SystemSecretGenerator(),
            )
            assert PostgresAdministrativeLoginStore(connection).load_candidate(
                email_lookup_digest=email_lookup.protect(STAFF_EMAIL).lookup_digest
            ) is None

        sender.outcome = "accepted"
        replaced = _request_reset(client)
        assert replaced["deliveryStatus"] == "accepted"
        new_token = _token(sender, 1)
        assert new_token != old_token
        with migrated_engine.connect() as connection:
            links = connection.execute(select(SecurityLink.status, SecurityLink.delivery_status, SecurityLink.expires_at, SecurityLink.issued_at).where(
                SecurityLink.admin_account_id == staff_id
            ).order_by(SecurityLink.security_link_id)).all()
            assert [(link.status, link.delivery_status) for link in links] == [
                ("invalidated", "failed"), ("active", "accepted")
            ]
            assert links[1].expires_at - links[1].issued_at == timedelta(minutes=30)
            assert connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == staff_id)).scalar_one() is None
        assert client.post("/api/admin/password-recovery/complete", json={"token": old_token, "newPassword": NEW_PASSWORD}).status_code == 400


@pytest.mark.integration
def test_t063_expired_link_is_retired_and_owner_can_issue_distinct_full_lifetime_link(migrated_engine: Engine) -> None:
    owner_id, staff_id = _seed(migrated_engine)
    sender = RecordingSender()
    with _client(migrated_engine, sender=sender, actor=AdministrativeActor(owner_id, "owner")) as client:
        assert _request_reset(client)["deliveryStatus"] == "accepted"
        expired_token = _token(sender, 0)
        with migrated_engine.begin() as connection:
            expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            connection.execute(update(SecurityLink).where(SecurityLink.admin_account_id == staff_id).values(
                expires_at=expired_at, issued_at=expired_at - timedelta(minutes=30)
            ))
        expired_response = client.post("/api/admin/password-recovery/complete", json={"token": expired_token, "newPassword": NEW_PASSWORD})
        assert expired_response.status_code == 400
        with migrated_engine.connect() as connection:
            assert connection.execute(select(SecurityLink.status).where(SecurityLink.admin_account_id == staff_id)).scalar_one() == "expired"
            assert connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == staff_id)).scalar_one() is None

        assert _request_reset(client)["deliveryStatus"] == "accepted"
        replacement_token = _token(sender, 1)
        assert replacement_token != expired_token
        with migrated_engine.connect() as connection:
            links = connection.execute(select(SecurityLink.status, SecurityLink.expires_at, SecurityLink.issued_at).where(
                SecurityLink.admin_account_id == staff_id
            ).order_by(SecurityLink.security_link_id)).all()
        assert [link.status for link in links] == ["expired", "active"]
        assert links[1].expires_at - links[1].issued_at == timedelta(minutes=30)
        assert client.post("/api/admin/password-recovery/complete", json={"token": expired_token, "newPassword": NEW_PASSWORD}).status_code == 400


@pytest.mark.integration
def test_t063_new_owner_order_invalidates_previous_accepted_link(migrated_engine: Engine) -> None:
    owner_id, staff_id = _seed(migrated_engine)
    sender = RecordingSender()
    with _client(migrated_engine, sender=sender, actor=AdministrativeActor(owner_id, "owner")) as client:
        assert _request_reset(client)["deliveryStatus"] == "accepted"
        first_token = _token(sender, 0)
        assert _request_reset(client)["deliveryStatus"] == "accepted"
        second_token = _token(sender, 1)
        assert second_token != first_token
        with migrated_engine.connect() as connection:
            assert connection.execute(select(SecurityLink.status).where(SecurityLink.admin_account_id == staff_id).order_by(SecurityLink.security_link_id)).scalars().all() == ["invalidated", "active"]
            assert connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == staff_id)).scalar_one() is None
        assert client.post("/api/admin/password-recovery/complete", json={"token": first_token, "newPassword": NEW_PASSWORD}).status_code == 400
