"""T070 PostgreSQL evidence for link-authorized, atomic factor replacement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select, update

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.confirm_totp_replacement import (
    ConfirmAdministrativeTotpReplacement,
)
from backend.app.application.admin_access.security_change_invalidation import (
    InvalidateAfterSecurityChange,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import FixedClock, SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import NotificationSendResult
from backend.app.infrastructure.persistence.admin_account_security_repository import PostgresAdministrativeAccountSecurityStore
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import PostgresAdministrativeLockRecipientDirectory
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAuditEvent,
    AdminSession,
    PendingSecuritySetup,
    RecoveryCode,
    SecurityLink,
    SecurityNotificationDelivery,
    TotpFactor,
)
from backend.app.infrastructure.persistence.security_change_invalidation_repository import PostgresSecurityChangeInvalidationStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.persistence.totp_replacement_confirmation_repository import PostgresTotpReplacementConfirmationStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration
from backend.app.web.admin_auth.security_link_transport import encode_security_link_token
from backend.app.web.admin_auth.totp_replacement_confirmation import (
    _PostgresTotpReplacementConfirmationOperation,
    get_totp_replacement_confirmation_operation,
    router,
)
from backend.app.web.admin_security_headers import register_administrative_security_headers
from backend.tests.integration.admin_access.test_totp_replacement_confirmation import (
    _FailingAuditStore,
    _protected_snapshot,
    replacement_engine,
)
from backend.tests.integration.admin_access.test_admin_login_session import (
    NOW,
    SECRET,
    migrated_engine,
)
from backend.tests.integration.admin_access.test_lost_factor_replacement_request import (
    _seed_account as _seed_configured_account,
)


class AcceptedEmail:
    def send(self, notification):
        return NotificationSendResult.accepted(notification.channel)


def _issue_link(engine: Engine, *, now: datetime | None = None) -> bytes:
    current_time = now or datetime.now(timezone.utc)
    key_ring = _ring()
    entropy = SystemSecretGenerator()
    with engine.begin() as connection:
        link = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(current_time),
            secret_generator=entropy,
            protector=SecurityLinkProtector(key_ring=key_ring),
        ).issue(account_id=1, purpose="totp_replacement")
        PostgresSecurityLinkStore(connection).mark_delivery_accepted(
            link_id=link.stored_link.link_id,
            current_time=current_time,
        )
    return link.token


def _app(engine: Engine):
    app = FastAPI()
    app.include_router(router)
    register_administrative_security_headers(app)
    app.dependency_overrides[get_totp_replacement_confirmation_operation] = lambda: _PostgresTotpReplacementConfirmationOperation(
        engine,
        email_sender=AcceptedEmail(),
    )
    return app


def _prepare(client: TestClient, token: bytes):
    response = client.post(
        "/api/admin/totp-replacement/prepare-lost",
        json={"token": encode_security_link_token(token)},
    )
    assert response.status_code == 200, response.text
    return response.json()["totpSetup"]["manualKey"]


def _confirm(client: TestClient, token: bytes, code: str):
    return client.post(
        "/api/admin/totp-replacement/complete-lost",
        json={"token": encode_security_link_token(token), "totpCode": code},
    )


def _seed(engine: Engine) -> None:
    account_id = _seed_configured_account(engine)
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    entropy = SystemSecretGenerator()
    factor = TotpFactorProtector(key_ring=key_ring, secret_generator=entropy).encrypt(
        account_id=account_id,
        secret=SECRET,
    )
    recovery_protector = RecoveryCodeProtector(key_ring=key_ring)
    values = ["ABCDEFGHJKLMNPQ" + suffix for suffix in "23456789AB"]
    with engine.begin() as connection:
        connection.execute(
            insert(TotpFactor).values(
                admin_account_id=account_id,
                totp_secret_ciphertext=factor,
                key_version=key_ring.key_version,
                algorithm="SHA1",
                digits=6,
                period_seconds=30,
                status="active",
                confirmed_at=NOW,
            )
        )
        connection.execute(
            insert(RecoveryCode),
            [
                {
                    "admin_account_id": account_id,
                    "lookup_digest": recovery_protector.digest(value),
                    "key_version": key_ring.key_version,
                    "position": position,
                    "status": "active",
                    "used_at": None,
                    "invalidated_at": None,
                }
                for position, value in enumerate(values, start=1)
            ],
        )
        connection.execute(
            insert(AdminSession).values(
                admin_account_id=account_id,
                session_digest=b"\x41" * 32,
                csrf_digest=b"\x42" * 32,
                key_version=key_ring.key_version,
                created_at=NOW - timedelta(hours=1),
                last_human_activity_at=NOW - timedelta(minutes=1),
                absolute_expires_at=NOW + timedelta(hours=7),
                status="active",
            )
        )


def _ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(load_cryptography_key_configuration())


def test_t070_success_replaces_factor_and_codes_once_and_creates_no_session(
    replacement_engine: Engine,
) -> None:
    _seed(replacement_engine)
    token = _issue_link(replacement_engine)
    app = _app(replacement_engine)

    with TestClient(app, base_url="http://testserver") as client:
        manual_key = _prepare(client, token)
        code = pyotp.TOTP(manual_key).now()
        response = _confirm(client, token, code)

    assert response.status_code == 200
    assert len(response.json()["recoveryCodes"]) == 10
    assert len(set(response.json()["recoveryCodes"])) == 10
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "set-cookie" not in response.headers
    with replacement_engine.connect() as connection:
        factors = connection.execute(
            select(TotpFactor.status, TotpFactor.totp_secret_ciphertext)
            .order_by(TotpFactor.totp_factor_id)
        ).all()
        assert factors[0].status == "invalidated" and factors[0].totp_secret_ciphertext is None
        assert factors[1].status == "active" and factors[1].totp_secret_ciphertext
        codes = connection.execute(
            select(RecoveryCode.status).order_by(RecoveryCode.recovery_code_id)
        ).scalars().all()
        assert codes[:10] == ["invalidated"] * 10
        assert codes[10:] == ["active"] * 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["invalidated"]
        assert connection.execute(select(func.count()).select_from(AdminSession)).scalar_one() == 1
        assert connection.execute(select(SecurityLink.status)).scalar_one() == "consumed"
        assert connection.execute(select(PendingSecuritySetup.status)).scalar_one() == "confirmed"
        assert connection.execute(
            select(AdminAuditEvent.action, AdminAuditEvent.result)
        ).all() == [("totp_replacement", "succeeded")]
        assert connection.execute(
            select(SecurityNotificationDelivery.event)
        ).scalars().all() == ["totp_replaced"]


def test_t070_audit_rollback_preserves_old_state_pending_setup_and_valid_link(
    replacement_engine: Engine,
) -> None:
    _seed(replacement_engine)
    token = _issue_link(replacement_engine)
    operation = _PostgresTotpReplacementConfirmationOperation(replacement_engine, email_sender=AcceptedEmail())
    manual_key = operation.prepare_lost_factor(token=token).manual_key
    now = datetime.now(timezone.utc)
    with replacement_engine.connect() as connection:
        old_state = _protected_snapshot(connection)
    code = pyotp.TOTP(manual_key).at(now)

    with pytest.raises(RuntimeError, match="synthetic audit"):
        with replacement_engine.begin() as connection:
            _confirm_use_case(connection, failing_audit=True).confirm_lost_factor(
                token=token,
                link_lifecycle=_links(connection),
                totp_code=code,
            )

    with replacement_engine.connect() as connection:
        assert _protected_snapshot(connection) == old_state
        assert connection.execute(select(TotpFactor.status)).scalars().all() == ["active"]
        assert connection.execute(select(RecoveryCode.status)).scalars().all() == ["active"] * 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        assert connection.execute(select(PendingSecuritySetup.status)).scalar_one() == "pending"
        assert connection.execute(select(SecurityLink.status)).scalar_one() == "active"
        assert connection.execute(select(AdminAuditEvent)).scalars().all() == []
        assert connection.execute(select(SecurityNotificationDelivery)).scalars().all() == []


def test_t070_wrong_new_code_discards_only_pending_setup_and_does_not_consume_link(
    replacement_engine: Engine,
) -> None:
    _seed(replacement_engine)
    token = _issue_link(replacement_engine)
    app = _app(replacement_engine)
    with TestClient(app, base_url="http://testserver") as client:
        _prepare(client, token)
        response = _confirm(client, token, "000000")

    assert response.status_code == 404
    assert response.json() == {"detail": "Este enlace o configuración no está disponible."}
    with replacement_engine.connect() as connection:
        assert connection.execute(select(TotpFactor.status)).scalars().all() == ["active"]
        assert connection.execute(select(RecoveryCode.status)).scalars().all() == ["active"] * 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        assert connection.execute(select(PendingSecuritySetup.status)).scalar_one() == "invalidated"
        assert connection.execute(select(SecurityLink.status)).scalar_one() == "active"


def test_t070_reused_link_cannot_confirm_twice(
    replacement_engine: Engine,
) -> None:
    _seed(replacement_engine)
    token = _issue_link(replacement_engine)
    app = _app(replacement_engine)
    with TestClient(app, base_url="http://testserver") as client:
        manual_key = _prepare(client, token)
        success = _confirm(client, token, pyotp.TOTP(manual_key).now())
        replay = _confirm(client, token, pyotp.TOTP(manual_key).now())

    assert success.status_code == 200
    assert replay.status_code == 404
    assert replay.json() == {"detail": "Este enlace o configuración no está disponible."}
    with replacement_engine.connect() as connection:
        assert connection.execute(select(SecurityLink.status)).scalar_one() == "consumed"
        assert connection.execute(select(func.count()).select_from(TotpFactor).where(TotpFactor.status == "active")).scalar_one() == 1
        assert connection.execute(select(func.count()).select_from(RecoveryCode).where(RecoveryCode.status == "active")).scalar_one() == 10
        assert connection.execute(select(func.count()).select_from(AdminSession)).scalar_one() == 1


def test_t070_expired_link_rejects_confirmation_without_changing_old_credentials(
    replacement_engine: Engine,
) -> None:
    _seed(replacement_engine)
    token = _issue_link(replacement_engine)
    operation = _PostgresTotpReplacementConfirmationOperation(replacement_engine, email_sender=AcceptedEmail())
    manual_key = operation.prepare_lost_factor(token=token).manual_key
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    issued_at = expired_at - timedelta(minutes=30)
    with replacement_engine.begin() as connection:
        connection.execute(
            update(SecurityLink).values(issued_at=issued_at, expires_at=expired_at)
        )
        connection.execute(
            update(PendingSecuritySetup).values(
                created_at=issued_at,
                expires_at=expired_at,
            )
        )
    code = pyotp.TOTP(manual_key).now()
    with replacement_engine.begin() as connection:
        outcome = _confirm_use_case(connection).confirm_lost_factor(
            token=token,
            link_lifecycle=_links(connection),
            totp_code=code,
        )

    assert outcome.status == "unavailable"
    with replacement_engine.connect() as connection:
        assert connection.execute(select(TotpFactor.status)).scalars().all() == ["active"]
        assert connection.execute(select(RecoveryCode.status)).scalars().all() == ["active"] * 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        assert connection.execute(select(SecurityLink.status)).scalar_one() == "expired"
        assert connection.execute(select(PendingSecuritySetup.status)).scalar_one() == "expired"


def test_t070_concurrent_confirmations_consume_the_link_and_replace_once(
    replacement_engine: Engine,
) -> None:
    _seed(replacement_engine)
    token = _issue_link(replacement_engine)
    operation = _PostgresTotpReplacementConfirmationOperation(replacement_engine, email_sender=AcceptedEmail())
    manual_key = operation.prepare_lost_factor(token=token).manual_key
    code = pyotp.TOTP(manual_key).now()
    barrier = Barrier(2)

    def confirm_once():
        barrier.wait(timeout=10)
        return operation.confirm_lost_factor(token=token, totp_code=code).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: confirm_once(), range(2)))

    assert sorted(outcomes) == ["replaced", "unavailable"]
    with replacement_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(TotpFactor).where(TotpFactor.status == "active")).scalar_one() == 1
        assert connection.execute(select(func.count()).select_from(RecoveryCode).where(RecoveryCode.status == "active")).scalar_one() == 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["invalidated"]
        assert connection.execute(select(SecurityLink.status)).scalar_one() == "consumed"
        assert connection.execute(select(func.count()).select_from(AdminAuditEvent).where(AdminAuditEvent.result == "succeeded")).scalar_one() == 1


def _links(connection):
    clock = SystemClock()
    key_ring = _ring()
    return SecurityLinkLifecycle(
        store=PostgresSecurityLinkStore(connection),
        clock=clock,
        secret_generator=SystemSecretGenerator(),
        protector=SecurityLinkProtector(key_ring=key_ring),
    )


def _confirm_use_case(connection, *, failing_audit: bool = False):
    clock = SystemClock()
    entropy = SystemSecretGenerator()
    key_ring = _ring()
    email = AdministrativeEmailProtector(key_ring=key_ring, secret_generator=entropy)
    security = PostgresAdministrativeAccountSecurityStore(connection)
    audit = RecordAdministrativeAuditEvent(
        store=_FailingAuditStore() if failing_audit else PostgresAdministrativeAuditStore(connection),
        clock=clock,
    )
    notifications = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(key_ring=key_ring, secret_generator=entropy),
    )
    failures = RecordProtectedAdministrativeCredentialFailure(
        failure_recorder=RecordAdministrativeCredentialFailure(store=security, clock=clock),
        audit=audit,
        notifications=notifications,
        recipients=PostgresAdministrativeLockRecipientDirectory(
            connection=connection,
            email_protector=email,
        ),
    )
    return ConfirmAdministrativeTotpReplacement(
        store=PostgresTotpReplacementConfirmationStore(connection, email),
        credential_guard=EnsureAdministrativeCredentialCheck(store=security, clock=clock),
        failure_recorder=failures,
        pending_factor_protector=PendingTotpProtector(key_ring=key_ring, secret_generator=entropy),
        factor_protector=TotpFactorProtector(key_ring=key_ring, secret_generator=entropy),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=key_ring),
        ),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection),
            clock=clock,
        ),
        audit=audit,
        notifications=notifications,
        clock=clock,
    )
