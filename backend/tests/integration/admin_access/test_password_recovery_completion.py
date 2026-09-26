"""T060 PostgreSQL journey and rollback evidence for password recovery."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, update

from backend.app.application.transactional_notifications import EMAIL_CHANNEL, NotificationSendResult, OutboundNotification
from backend.app.application.admin_access.account_security import CheckPostRecoveryFactorReplacement
from backend.app.infrastructure.persistence.admin_account_security_repository import PostgresAdministrativeAccountSecurityStore
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.models import AdminAccount, AdminAccountSecurityState, AdminAuditEvent, AdminCredentialFailureEvent, AdminEmailClaim, AdminSession, RecoveryCode, SecurityLink, TotpFactor
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration
from backend.app.web.admin_auth.password_recovery_request import PostgresPasswordRecoveryOperations, router as request_router, get_password_recovery_operations
from backend.app.web.admin_auth.password_recovery_completion import _PostgresPasswordRecoveryCompletionOperation, router as completion_router, get_password_recovery_completion_operations
from backend.app.web.admin_auth import password_recovery_completion as completion_web
from backend.app.web.admin_auth.security_link_transport import decode_security_link_token
from backend.app.web.admin_security_headers import register_administrative_security_headers
from backend.tests.integration.admin_access.test_admin_login_session import migrated_engine


EMAIL = "synthetic.recovery@example.test"
OLD_PASSWORD = "synthetic previous password phrase"
NEW_PASSWORD = "synthetic replacement phrase"
FACTOR_SECRET = b"JBSWY3DPEHPK3PXP"


class RecordingSender:
    def __init__(self) -> None:
        self.notifications: list[OutboundNotification] = []

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.notifications.append(notification)
        return NotificationSendResult.accepted(notification.channel)


def _seed(engine: Engine) -> int:
    ring = CryptographyKeyRing(load_cryptography_key_configuration())
    entropy = SystemSecretGenerator()
    email = AdministrativeEmailProtector(key_ring=ring, secret_generator=entropy).protect(EMAIL)
    factor = TotpFactorProtector(key_ring=ring, secret_generator=entropy).encrypt(account_id=1, secret=FACTOR_SECRET)
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount).values(
                role="owner", status="active", password_hash=AdministrativePasswordHasher().hash_password(OLD_PASSWORD)
            ).returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(insert(AdminEmailClaim).values(
            admin_account_id=account_id, claim_kind="current", lookup_digest=email.lookup_digest,
            email_ciphertext=email.email_ciphertext, key_version=email.key_version,
        ))
        connection.execute(insert(TotpFactor).values(
            admin_account_id=account_id, totp_secret_ciphertext=factor,
            key_version=load_cryptography_key_configuration().key_version, algorithm="SHA1", digits=6, period_seconds=30,
            status="active", confirmed_at=datetime.now(timezone.utc),
        ))
        connection.execute(insert(RecoveryCode).values(
            admin_account_id=account_id, lookup_digest=b"\x43" * 32,
            key_version=load_cryptography_key_configuration().key_version,
            position=1, status="active",
        ))
        now = datetime.now(timezone.utc)
        connection.execute(insert(AdminSession).values(
            admin_account_id=account_id, session_digest=b"\x41" * 32, csrf_digest=b"\x42" * 32,
            key_version=load_cryptography_key_configuration().key_version, created_at=now, last_human_activity_at=now,
            absolute_expires_at=now + timedelta(hours=8), status="active",
        ))
    return account_id


def _lock_account(engine: Engine, *, account_id: int) -> tuple[datetime, int, tuple[int, ...]]:
    """Seed the fifth recent credential failure and its exact active lock."""

    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        event_ids = connection.execute(
            insert(AdminCredentialFailureEvent)
            .values([
                {"admin_account_id": account_id, "operation": "login", "occurred_at": now - timedelta(minutes=2, seconds=offset)}
                for offset in range(5)
            ])
            .returning(AdminCredentialFailureEvent.admin_credential_failure_event_id)
        ).scalars().all()
        lock_until = now + timedelta(minutes=13)
        connection.execute(update(AdminAccountSecurityState).where(
            AdminAccountSecurityState.admin_account_id == account_id,
        ).values(lock_until=lock_until, fifth_failure_event_id=event_ids[-1]))
    return lock_until, event_ids[-1], tuple(event_ids)


def _client(engine: Engine, sender: RecordingSender) -> TestClient:
    app = FastAPI()
    app.include_router(request_router)
    app.include_router(completion_router)
    register_administrative_security_headers(app)
    app.dependency_overrides[get_password_recovery_operations] = lambda: PostgresPasswordRecoveryOperations(engine=engine, email_sender=sender)
    app.dependency_overrides[get_password_recovery_completion_operations] = lambda: _PostgresPasswordRecoveryCompletionOperation(engine=engine, email_sender=sender)
    return TestClient(app)


def _issue(client: TestClient, sender: RecordingSender) -> tuple[str, bytes]:
    response = client.post("/api/admin/password-recovery", json={"email": EMAIL})
    assert response.status_code == 202
    match = re.search(r"#token=([A-Za-z0-9_-]{43})", sender.notifications[-1].content)
    assert match is not None
    return match.group(1), decode_security_link_token(match.group(1))


@pytest.mark.integration
def test_t061_request_and_completion_preserve_failures_and_lock_for_locked_account(migrated_engine: Engine) -> None:
    account_id = _seed(migrated_engine)
    lock_until, fifth_failure_id, failure_ids = _lock_account(migrated_engine, account_id=account_id)
    sender = RecordingSender()
    with _client(migrated_engine, sender) as client:
        encoded, _token = _issue(client, sender)
        with migrated_engine.connect() as connection:
            assert connection.execute(select(AdminAccountSecurityState.lock_until).where(AdminAccountSecurityState.admin_account_id == account_id)).scalar_one() == lock_until
            assert connection.execute(select(AdminCredentialFailureEvent.admin_credential_failure_event_id).where(AdminCredentialFailureEvent.admin_account_id == account_id).order_by(AdminCredentialFailureEvent.admin_credential_failure_event_id)).scalars().all() == list(failure_ids)
        response = client.post("/api/admin/password-recovery/complete", json={"token": encoded, "newPassword": NEW_PASSWORD})

    assert response.status_code == 204
    assert response.content == b""
    assert "set-cookie" not in response.headers
    assert len(sender.notifications) == 2
    assert sender.notifications[1].channel == EMAIL_CHANNEL
    assert sender.notifications[1].recipient == EMAIL
    assert "token" not in sender.notifications[1].content.lower()
    with migrated_engine.connect() as connection:
        password_hash = connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == account_id)).scalar_one()
        assert connection.execute(select(AdminSession.status).where(AdminSession.admin_account_id == account_id)).scalars().all() == ["invalidated"]
        assert connection.execute(select(SecurityLink.status).where(SecurityLink.purpose == "password_recovery")).scalar_one() == "consumed"
        assert connection.execute(select(TotpFactor.status).where(TotpFactor.admin_account_id == account_id)).scalar_one() == "active"
        assert connection.execute(select(RecoveryCode.status).where(RecoveryCode.admin_account_id == account_id)).scalars().all() == ["active"]
        assert connection.execute(select(AdminAuditEvent.action, AdminAuditEvent.result).where(AdminAuditEvent.action == "password_recovery")).all() == [("password_recovery", "succeeded")]
        assert connection.execute(select(AdminAccountSecurityState.lock_until, AdminAccountSecurityState.fifth_failure_event_id, AdminAccountSecurityState.post_recovery_second_factor_restricted).where(AdminAccountSecurityState.admin_account_id == account_id)).one() == (lock_until, fifth_failure_id, True)
        assert not CheckPostRecoveryFactorReplacement(
            store=PostgresAdministrativeAccountSecurityStore(connection)
        ).is_allowed(account_id=account_id)
        assert connection.execute(select(AdminCredentialFailureEvent.admin_credential_failure_event_id).where(AdminCredentialFailureEvent.admin_account_id == account_id).order_by(AdminCredentialFailureEvent.admin_credential_failure_event_id)).scalars().all() == list(failure_ids)
    hasher = AdministrativePasswordHasher()
    assert hasher.verify_and_upgrade(stored_hash=password_hash, password=NEW_PASSWORD).verified
    assert not hasher.verify_and_upgrade(stored_hash=password_hash, password=OLD_PASSWORD).verified


@pytest.mark.integration
def test_t060_invalid_password_preserves_existing_password_and_link(migrated_engine: Engine) -> None:
    account_id = _seed(migrated_engine)
    sender = RecordingSender()
    with _client(migrated_engine, sender) as client:
        encoded, _token = _issue(client, sender)
        before = client.post("/api/admin/password-recovery/complete", json={"token": encoded, "newPassword": "short"})
    assert before.status_code == 422
    with migrated_engine.connect() as connection:
        assert connection.execute(select(SecurityLink.status).where(SecurityLink.purpose == "password_recovery")).scalar_one() == "active"
        password_hash = connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == account_id)).scalar_one()
        assert connection.execute(select(AdminSession.status).where(AdminSession.admin_account_id == account_id)).scalar_one() == "active"
        assert not connection.execute(select(AdminAccountSecurityState.post_recovery_second_factor_restricted).where(AdminAccountSecurityState.admin_account_id == account_id)).scalar_one()
        assert connection.execute(select(AdminAuditEvent.action).where(AdminAuditEvent.action == "password_recovery")).all() == []
    assert AdministrativePasswordHasher().verify_and_upgrade(stored_hash=password_hash, password=OLD_PASSWORD).verified


@pytest.mark.integration
def test_t060_failure_after_mutations_rolls_back_credentials_and_link(migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    account_id = _seed(migrated_engine)
    sender = RecordingSender()
    with _client(migrated_engine, sender) as client:
        encoded, token = _issue(client, sender)
    original_compose = completion_web._compose_completion

    def fail_after_database_mutations(connection):
        operation = original_compose(connection)
        invalidator = operation._invalidator

        class FailingInvalidator:
            def execute(self, *, account_id: int) -> None:
                invalidator.execute(account_id=account_id)
                raise RuntimeError("synthetic failure after credential mutation")

        operation._invalidator = FailingInvalidator()
        return operation

    monkeypatch.setattr(completion_web, "_compose_completion", fail_after_database_mutations)
    operation = _PostgresPasswordRecoveryCompletionOperation(migrated_engine, email_sender=sender)
    with pytest.raises(RuntimeError):
        operation.complete(token=token, new_password=NEW_PASSWORD)

    with migrated_engine.connect() as connection:
        password_hash = connection.execute(select(AdminAccount.password_hash).where(AdminAccount.admin_account_id == account_id)).scalar_one()
        assert connection.execute(select(SecurityLink.status).where(SecurityLink.purpose == "password_recovery")).scalar_one() == "active"
        assert connection.execute(select(AdminSession.status).where(AdminSession.admin_account_id == account_id)).scalar_one() == "active"
        assert not connection.execute(select(AdminAccountSecurityState.post_recovery_second_factor_restricted).where(AdminAccountSecurityState.admin_account_id == account_id)).scalar_one()
        assert connection.execute(select(AdminAuditEvent.action).where(AdminAuditEvent.action == "password_recovery")).all() == []
    hasher = AdministrativePasswordHasher()
    assert hasher.verify_and_upgrade(stored_hash=password_hash, password=OLD_PASSWORD).verified
    assert not hasher.verify_and_upgrade(stored_hash=password_hash, password=NEW_PASSWORD).verified
    assert len(sender.notifications) == 1


@pytest.mark.integration
def test_t060_concurrent_completion_consumes_link_once(migrated_engine: Engine) -> None:
    _seed(migrated_engine)
    sender = RecordingSender()
    with _client(migrated_engine, sender) as client:
        _encoded, token = _issue(client, sender)
    barrier = Barrier(2)

    def complete(password: str) -> str:
        barrier.wait(timeout=5)
        try:
            return _PostgresPasswordRecoveryCompletionOperation(migrated_engine, email_sender=sender).complete(
                token=token, new_password=password
            )
        except Exception:
            return "error"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(complete, (NEW_PASSWORD, "another synthetic password phrase")))
    assert sorted(results) == ["completed", "invalid_link"]
    with migrated_engine.connect() as connection:
        assert connection.execute(select(SecurityLink.status).where(SecurityLink.purpose == "password_recovery")).scalar_one() == "consumed"
        assert connection.execute(select(AdminAuditEvent.result).where(AdminAuditEvent.action == "password_recovery")).scalars().all() == ["succeeded"]
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["invalidated"]
    assert len(sender.notifications) == 2
