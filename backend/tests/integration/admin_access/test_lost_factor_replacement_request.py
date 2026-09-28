"""T069 PostgreSQL evidence for eligible, generic lost-factor requests."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select, text, update

from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.public_request_limit import AllowPublicRequests
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminCredentialFailureEvent,
    AdminEmailClaim,
    RecoveryCode,
    SecurityLink,
    RateLimitEvent,
    TotpFactor,
)
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.administrative_rate_limit_subject import (
    AdministrativeRateLimitSubjectProtector,
)
from backend.app.domain.authentication.rate_limit import SECURITY_MESSAGE_ACTION_LIMIT
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_test_database_url,
)
from backend.app.web.admin_auth.lost_factor_replacement_request import (
    PostgresLostFactorReplacementRequestOperations,
    get_lost_factor_replacement_request_operations,
    router,
)
from backend.app.web.admin_auth.password_recovery_completion import (
    _PostgresPasswordRecoveryCompletionOperation,
    get_password_recovery_completion_operations,
    router as password_recovery_completion_router,
)
from backend.app.web.admin_auth.password_recovery_request import (
    PostgresPasswordRecoveryOperations,
    get_password_recovery_operations,
    router as password_recovery_request_router,
)
from backend.app.web.admin_auth.security_link_transport import decode_security_link_token
from backend.app.web.admin_security_headers import register_administrative_security_headers
from backend.app.web.public_request_protection import (
    get_public_authentication_request_limiter,
)


ROOT = Path(__file__).resolve().parents[4]
EMAIL = "synthetic.lost-factor@example.test"
PASSWORD = "synthetic correct password"
PATH = "/api/admin/totp-replacement/request"
GENERIC_MESSAGE = "Si la cuenta puede iniciar el reemplazo del segundo factor, recibirás instrucciones en el correo registrado."
@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE admin_accounts, owner_bootstrap_state, rate_limit_events, rate_limit_guards RESTART IDENTITY CASCADE"))
            connection.execute(text("INSERT INTO owner_bootstrap_state (bootstrap_state_id, status) VALUES (1, 'open')"))
        yield engine
    finally:
        engine.dispose()


class RecordingEmailSender:
    def __init__(self) -> None:
        self.notifications: list[OutboundNotification] = []
        self._lock = threading.Lock()

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        with self._lock:
            self.notifications.append(notification)
        return NotificationSendResult.accepted(notification.channel)


def _seed_account(
    engine: Engine,
    *,
    status: str = "active",
    lock_until: datetime | None = None,
    restricted: bool = False,
) -> int:
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    protector = AdministrativeEmailProtector(
        key_ring=key_ring, secret_generator=SystemSecretGenerator()
    )
    protected_email = protector.protect(EMAIL)
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount)
            .values(
                role="owner" if status in {"active", "inactive"} else "staff",
                status=status,
                password_hash=AdministrativePasswordHasher().hash_password(PASSWORD),
            )
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=account_id,
                claim_kind="current",
                lookup_digest=protected_email.lookup_digest,
                email_ciphertext=protected_email.email_ciphertext,
                key_version=protected_email.key_version,
            )
        )
        failure_ids = []
        if lock_until is not None:
            failure_ids = [
                connection.execute(
                    insert(AdminCredentialFailureEvent)
                    .values(
                        admin_account_id=account_id,
                        operation="login",
                        occurred_at=datetime.now(timezone.utc)
                        - timedelta(minutes=5 - index),
                    )
                    .returning(AdminCredentialFailureEvent.admin_credential_failure_event_id)
                ).scalar_one()
                for index in range(5)
            ]
        connection.execute(
            update(AdminAccountSecurityState)
            .where(AdminAccountSecurityState.admin_account_id == account_id)
            .values(
                lock_until=lock_until,
                fifth_failure_event_id=None if not failure_ids else failure_ids[-1],
                post_recovery_second_factor_restricted=restricted,
            )
        )
    return account_id


def _app(engine: Engine, sender: RecordingEmailSender) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    register_administrative_security_headers(app)
    app.dependency_overrides[get_lost_factor_replacement_request_operations] = lambda: PostgresLostFactorReplacementRequestOperations(
        engine=engine, email_sender=sender
    )
    app.dependency_overrides[get_public_authentication_request_limiter] = (
        AllowPublicRequests
    )
    return app


def _password_recovery_chain_app(engine: Engine, sender: RecordingEmailSender) -> FastAPI:
    app = FastAPI()
    app.include_router(password_recovery_request_router)
    app.include_router(password_recovery_completion_router)
    app.include_router(router)
    register_administrative_security_headers(app)
    app.dependency_overrides[get_password_recovery_operations] = lambda: PostgresPasswordRecoveryOperations(
        engine=engine, email_sender=sender
    )
    app.dependency_overrides[get_public_authentication_request_limiter] = (
        AllowPublicRequests
    )
    app.dependency_overrides[get_password_recovery_completion_operations] = lambda: _PostgresPasswordRecoveryCompletionOperation(
        engine=engine, email_sender=sender
    )
    app.dependency_overrides[get_lost_factor_replacement_request_operations] = lambda: PostgresLostFactorReplacementRequestOperations(
        engine=engine, email_sender=sender
    )
    return app


def _request(client: TestClient, *, email: str = EMAIL, password: str = PASSWORD):
    return client.post(PATH, json={"email": email, "password": password})


def _token(sender: RecordingEmailSender) -> bytes:
    content = sender.notifications[-1].content
    assert "/admin/totp-replacement#token=" in content
    match = re.search(r"#token=([A-Za-z0-9_-]{43})", content)
    assert match is not None
    return decode_security_link_token(match.group(1))


def _link_rows(engine: Engine, account_id: int):
    with engine.connect() as connection:
        return list(
            connection.execute(
                select(
                    SecurityLink.status,
                    SecurityLink.delivery_status,
                    SecurityLink.issued_at,
                    SecurityLink.expires_at,
                    SecurityLink.token_digest,
                )
                .where(
                    SecurityLink.admin_account_id == account_id,
                    SecurityLink.purpose == "totp_replacement",
                )
                .order_by(SecurityLink.security_link_id)
            ).all()
        )


def test_t069_correct_credentials_issue_one_opaque_30_minute_link_and_reissue_replaces_it(
    migrated_engine: Engine,
) -> None:
    account_id = _seed_account(migrated_engine)
    sender = RecordingEmailSender()
    app = _app(migrated_engine, sender)

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        first = _request(client)
        first_token = _token(sender)
        second = _request(client)
        second_token = _token(sender)

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json() == {"message": GENERIC_MESSAGE}
    assert (first.content, dict(first.headers)) == (second.content, dict(second.headers))
    assert first_token != second_token
    assert len(sender.notifications) == 2
    assert all(item.channel == EMAIL_CHANNEL and item.recipient == EMAIL for item in sender.notifications)
    assert all(EMAIL not in item.content and "30 minutos" in item.content for item in sender.notifications)
    rows = _link_rows(migrated_engine, account_id)
    assert [(row.status, row.delivery_status) for row in rows] == [
        ("invalidated", "accepted"),
        ("active", "accepted"),
    ]
    assert all(row.expires_at - row.issued_at == timedelta(minutes=30) for row in rows)
    assert sum(row.status == "active" for row in rows) == 1
    link_protector = SecurityLinkProtector(
        key_ring=CryptographyKeyRing(load_cryptography_key_configuration())
    )
    assert [row.token_digest for row in rows] == [
        link_protector.digest(first_token),
        link_protector.digest(second_token),
    ]


@pytest.mark.parametrize("failure", ["missing", "wrong_password", "locked", "restricted", "inactive", "invalid_email"])
def test_t069_ineligible_requests_are_generic_and_do_not_issue_or_replace_links(
    migrated_engine: Engine,
    failure: str,
) -> None:
    expected_lock_until = None
    if failure == "missing":
        account_id = None
    elif failure == "locked":
        expected_lock_until = datetime.now(timezone.utc) + timedelta(minutes=12)
        account_id = _seed_account(
            migrated_engine,
            lock_until=expected_lock_until,
        )
    elif failure == "restricted":
        account_id = _seed_account(migrated_engine, restricted=True)
    elif failure == "inactive":
        account_id = _seed_account(migrated_engine, status="deactivated")
    else:
        account_id = _seed_account(migrated_engine)

    sender = RecordingEmailSender()
    app = _app(migrated_engine, sender)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        valid_response = _request(client)
        valid_message = (valid_response.status_code, valid_response.content, dict(valid_response.headers))
        # Retire the setup link so an invalid request must preserve it rather than replacing it.
        if account_id is not None:
            with migrated_engine.begin() as connection:
                connection.execute(
                    update(SecurityLink)
                    .where(SecurityLink.admin_account_id == account_id)
                    .values(status="invalidated", invalidated_at=datetime.now(timezone.utc))
                )
            baseline_links = _link_rows(migrated_engine, account_id)
        else:
            baseline_links = []
        sender.notifications.clear()
        if failure == "missing":
            response = _request(client, email="synthetic.absent@example.test")
        elif failure == "wrong_password":
            response = _request(client, password="synthetic incorrect password")
        elif failure == "invalid_email":
            response = _request(client, email="not-an-email")
        else:
            response = _request(client)

    assert (response.status_code, response.content, dict(response.headers)) == valid_message
    assert sender.notifications == []
    if account_id is not None:
        assert _link_rows(migrated_engine, account_id) == baseline_links
    if failure == "wrong_password":
        with migrated_engine.connect() as connection:
            events = connection.execute(
                select(AdminCredentialFailureEvent.operation).where(
                    AdminCredentialFailureEvent.admin_account_id == account_id
                )
            ).scalars().all()
        assert events == ["totp_replacement"]
    if failure == "locked":
        with migrated_engine.connect() as connection:
            lock_until = connection.execute(
                select(AdminAccountSecurityState.lock_until).where(
                    AdminAccountSecurityState.admin_account_id == account_id
                )
            ).scalar_one()
        assert lock_until == expected_lock_until
        with migrated_engine.connect() as connection:
            failures = connection.execute(
                select(AdminCredentialFailureEvent.admin_credential_failure_event_id).where(
                    AdminCredentialFailureEvent.admin_account_id == account_id
                )
            ).scalars().all()
        assert len(failures) == 5


@pytest.mark.integration
@pytest.mark.parametrize("body", [{"email": EMAIL}, {"email": EMAIL, "password": ""}])
def test_t071_lost_factor_request_cannot_proceed_without_a_current_password(
    migrated_engine: Engine,
    body: dict[str, str],
) -> None:
    account_id = _seed_account(migrated_engine)
    sender = RecordingEmailSender()
    with TestClient(_app(migrated_engine, sender), client=("127.0.0.1", 50000)) as client:
        response = client.post(PATH, json=body)

    assert response.status_code == 422
    assert sender.notifications == []
    assert _link_rows(migrated_engine, account_id) == []


def test_t069_expired_link_is_expired_before_a_fresh_full_ttl_link_is_issued(
    migrated_engine: Engine,
) -> None:
    account_id = _seed_account(migrated_engine)
    sender = RecordingEmailSender()
    app = _app(migrated_engine, sender)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        _request(client)
        with migrated_engine.begin() as connection:
            connection.execute(
                update(SecurityLink)
                .where(SecurityLink.admin_account_id == account_id)
                .values(
                    issued_at=datetime.now(timezone.utc) - timedelta(minutes=31),
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                )
            )
        _request(client)

    rows = _link_rows(migrated_engine, account_id)
    assert [(row.status, row.delivery_status) for row in rows] == [
        ("expired", "accepted"),
        ("active", "accepted"),
    ]
    assert rows[1].expires_at - rows[1].issued_at == timedelta(minutes=30)
    assert sum(row.status == "active" for row in rows) == 1


@pytest.mark.integration
def test_t071_password_recovery_cannot_chain_into_lost_factor_replacement_without_old_factor(
    migrated_engine: Engine,
) -> None:
    account_id = _seed_account(migrated_engine)
    sender = RecordingEmailSender()
    app = _password_recovery_chain_app(migrated_engine, sender)
    new_password = "synthetic recovered password phrase"

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        recovery = client.post(
            "/api/admin/password-recovery", json={"email": EMAIL}
        )
        token_match = re.search(r"#token=([A-Za-z0-9_-]{43})", sender.notifications[0].content)
        assert recovery.status_code == 202
        assert token_match is not None
        completion = client.post(
            "/api/admin/password-recovery/complete",
            json={"token": token_match.group(1), "newPassword": new_password},
        )
        assert completion.status_code == 204
        assert "set-cookie" not in completion.headers

        notices_before_lost_factor_requests = len(sender.notifications)
        chained = _request(client, password=new_password)
        wrong_password = _request(client, password="synthetic incorrect password")
        missing_account = _request(
            client,
            email="synthetic.absent@example.test",
            password=new_password,
        )

    assert chained.status_code == wrong_password.status_code == missing_account.status_code == 202
    assert chained.json() == wrong_password.json() == missing_account.json() == {
        "message": GENERIC_MESSAGE
    }
    assert (chained.content, dict(chained.headers)) == (
        wrong_password.content,
        dict(wrong_password.headers),
    )
    assert (chained.content, dict(chained.headers)) == (
        missing_account.content,
        dict(missing_account.headers),
    )
    assert len(sender.notifications) == notices_before_lost_factor_requests
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminAccountSecurityState.post_recovery_second_factor_restricted)
            .where(AdminAccountSecurityState.admin_account_id == account_id)
        ).scalar_one()
        assert connection.execute(
            select(SecurityLink.security_link_id).where(
                SecurityLink.admin_account_id == account_id,
                SecurityLink.purpose == "totp_replacement",
            )
        ).all() == []
        assert connection.execute(
            select(TotpFactor.totp_factor_id).where(
                TotpFactor.admin_account_id == account_id
            )
        ).all() == []
        assert connection.execute(
            select(RecoveryCode.recovery_code_id).where(
                RecoveryCode.admin_account_id == account_id
            )
        ).all() == []


@pytest.mark.integration
def test_t093_password_recovery_and_lost_factor_share_one_account_message_budget(
    migrated_engine: Engine,
) -> None:
    account_id = _seed_account(migrated_engine)
    sender = RecordingEmailSender()
    app = _password_recovery_chain_app(migrated_engine, sender)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        for _ in range(5):
            recovery = client.post(
                "/api/admin/password-recovery", json={"email": EMAIL}
            )
            lost_factor = _request(client)
            assert recovery.status_code == lost_factor.status_code == 202
            assert recovery.json() == {
                "message": "Si existe una cuenta activa con ese correo, recibirás instrucciones para recuperar tu contraseña."
            }
            assert lost_factor.json() == {"message": GENERIC_MESSAGE}

        assert len(sender.notifications) == 10
        eleventh = _request(client)

    subject = AdministrativeRateLimitSubjectProtector(
        key_ring=CryptographyKeyRing(load_cryptography_key_configuration())
    ).fingerprint_account(account_id)
    with migrated_engine.connect() as connection:
        count = connection.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.category == SECURITY_MESSAGE_ACTION_LIMIT.category,
                RateLimitEvent.subject_fingerprint == subject,
            )
        ).scalar_one()
        failures = connection.execute(
            select(func.count())
            .select_from(AdminCredentialFailureEvent)
            .where(AdminCredentialFailureEvent.admin_account_id == account_id)
        ).scalar_one()

    assert eleventh.status_code == 202
    assert eleventh.json() == {"message": GENERIC_MESSAGE}
    assert len(sender.notifications) == 10
    assert count == 10
    assert failures == 0
