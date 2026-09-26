"""T058 PostgreSQL evidence: current, active claims alone yield recovery intents."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, text

from backend.app.application.admin_access.password_recovery_request import (
    PasswordRecoveryIntent,
    RequestAdministrativePasswordRecovery,
)
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_password_recovery_request_repository import (
    PostgresAdministrativeRecoveryAccountStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAuditEvent,
    AdminEmailClaim,
    SecurityLink,
)
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_test_database_url,
)
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.web.admin_auth.password_recovery_request import (
    get_password_recovery_operations,
    PostgresPasswordRecoveryOperations,
    router,
)
from backend.app.web.admin_auth.security_link_transport import (
    decode_security_link_token,
)
from backend.app.web.admin_security_headers import register_administrative_security_headers


ROOT = Path(__file__).resolve().parents[4]
ACTIVE_EMAIL = "synthetic.active@example.test"
PASSWORD_RECOVERY_PATH = "/admin/password-recovery"


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE admin_accounts, owner_bootstrap_state RESTART IDENTITY CASCADE"))
            connection.execute(text("INSERT INTO owner_bootstrap_state (bootstrap_state_id, status) VALUES (1, 'open')"))
        yield engine
    finally:
        engine.dispose()


class _RecordingEmailSender:
    def __init__(self, outcome: str = "accepted") -> None:
        self.outcome = outcome
        self.notifications: list[OutboundNotification] = []
        self._lock = threading.Lock()

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        with self._lock:
            self.notifications.append(notification)
            outcome = self.outcome
        if outcome == "raise":
            raise RuntimeError("synthetic provider failure")
        if outcome == "failed":
            return NotificationSendResult.failed(notification.channel)
        return NotificationSendResult.accepted(notification.channel)


def _seed_active_account(engine: Engine, protector: AdministrativeEmailProtector) -> int:
    email = protector.protect(ACTIVE_EMAIL)
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount)
            .values(
                role="owner",
                status="active",
                password_hash=AdministrativePasswordHasher().hash_password(
                    "synthetic current password"
                ),
            )
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=account_id,
                claim_kind="current",
                lookup_digest=email.lookup_digest,
                email_ciphertext=email.email_ciphertext,
                key_version=email.key_version,
            )
        )
    return account_id


def _test_operations(engine: Engine, sender: _RecordingEmailSender):
    return PostgresPasswordRecoveryOperations(engine=engine, email_sender=sender)


def _make_app(engine: Engine, sender: _RecordingEmailSender) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    register_administrative_security_headers(app)
    app.dependency_overrides[get_password_recovery_operations] = lambda: _test_operations(
        engine, sender
    )
    return app


def _captured_token(sender: _RecordingEmailSender) -> tuple[str, bytes]:
    content = sender.notifications[-1].content
    assert PASSWORD_RECOVERY_PATH in content
    match = re.search(r"#token=([A-Za-z0-9_-]{43})", content)
    assert match is not None
    encoded = match.group(1)
    return encoded, decode_security_link_token(encoded)


def _link_rows(engine: Engine, account_id: int) -> list[tuple[str, str, datetime, datetime, bytes]]:
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
                    SecurityLink.purpose == "password_recovery",
                )
                .order_by(SecurityLink.security_link_id)
            ).all()
        )


def test_t059_active_account_receives_one_opaque_30_minute_link_and_reissue_replaces_it(
    migrated_engine: Engine,
) -> None:
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    email_protector = AdministrativeEmailProtector(
        key_ring=key_ring,
        secret_generator=SystemSecretGenerator(),
    )
    account_id = _seed_active_account(migrated_engine, email_protector)
    sender = _RecordingEmailSender()
    app = _make_app(migrated_engine, sender)

    with TestClient(app) as client:
        first = client.post("/api/admin/password-recovery", json={"email": ACTIVE_EMAIL})
        first_token_text, first_token = _captured_token(sender)
        first_response = (first.status_code, first.content, dict(first.headers))
        second = client.post("/api/admin/password-recovery", json={"email": ACTIVE_EMAIL})
        second_token_text, second_token = _captured_token(sender)
        absent = client.post(
            "/api/admin/password-recovery",
            json={"email": "synthetic.absent@example.test"},
        )

    assert first_response[0] == 202
    assert first_response[1] == second.content
    assert first_response[2] == dict(second.headers)
    assert first_response == (absent.status_code, absent.content, dict(absent.headers))
    assert first_token != second_token
    assert first_token_text != second_token_text
    assert len(sender.notifications) == 2
    assert all(message.channel == EMAIL_CHANNEL for message in sender.notifications)
    assert all(message.recipient == ACTIVE_EMAIL for message in sender.notifications)
    assert all("30 minutos" in message.content for message in sender.notifications)
    assert all(ACTIVE_EMAIL not in message.content for message in sender.notifications)
    rows = _link_rows(migrated_engine, account_id)
    assert len(rows) == 2
    assert [(row.status, row.delivery_status) for row in rows] == [
        ("invalidated", "accepted"),
        ("active", "accepted"),
    ]
    assert all((row.expires_at - row.issued_at).total_seconds() == 30 * 60 for row in rows)
    link_protector = SecurityLinkProtector(key_ring=key_ring)
    assert rows[0].token_digest == link_protector.digest(first_token)
    assert rows[1].token_digest == link_protector.digest(second_token)
    assert sum(row.status == "active" for row in rows) == 1
    assert ACTIVE_EMAIL not in repr(rows)
    assert first_token_text not in repr(rows)
    assert second_token_text not in repr(rows)


@pytest.mark.parametrize("provider_outcome", ["failed", "raise"])
def test_t059_delivery_failure_invalidates_link_and_keeps_the_generic_response(
    migrated_engine: Engine,
    provider_outcome: str,
) -> None:
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    email_protector = AdministrativeEmailProtector(
        key_ring=key_ring,
        secret_generator=SystemSecretGenerator(),
    )
    account_id = _seed_active_account(migrated_engine, email_protector)
    sender = _RecordingEmailSender(provider_outcome)
    app = _make_app(migrated_engine, sender)

    with TestClient(app) as client:
        active_response = client.post(
            "/api/admin/password-recovery", json={"email": ACTIVE_EMAIL}
        )
        failed_token_text, _ = _captured_token(sender)
        absent_response = client.post(
            "/api/admin/password-recovery",
            json={"email": "synthetic.absent@example.test"},
        )

    assert (active_response.status_code, active_response.content, dict(active_response.headers)) == (
        absent_response.status_code,
        absent_response.content,
        dict(absent_response.headers),
    )
    assert len(sender.notifications) == 1
    rows = _link_rows(migrated_engine, account_id)
    assert len(rows) == 1
    assert (rows[0].status, rows[0].delivery_status) == ("invalidated", "failed")
    assert failed_token_text not in repr(rows)
    with migrated_engine.connect() as connection:
        failures = connection.execute(
            select(
                AdminAuditEvent.actor_account_id,
                AdminAuditEvent.target_reference,
            ).where(
                AdminAuditEvent.action == "password_recovery",
                AdminAuditEvent.result == "failed",
            )
        ).all()
        assert len(failures) == 1
        assert failures[0].actor_account_id is None
        assert failures[0].target_reference is None

    sender.outcome = "accepted"
    with TestClient(app) as client:
        retry = client.post("/api/admin/password-recovery", json={"email": ACTIVE_EMAIL})
    retry_token_text, _ = _captured_token(sender)
    rows = _link_rows(migrated_engine, account_id)
    assert retry.status_code == 202
    assert failed_token_text != retry_token_text
    assert len(sender.notifications) == 2
    assert [(row.status, row.delivery_status) for row in rows] == [
        ("invalidated", "failed"),
        ("active", "accepted"),
    ]


def test_t059_concurrent_requests_leave_at_most_one_active_recovery_link(
    migrated_engine: Engine,
) -> None:
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    email_protector = AdministrativeEmailProtector(
        key_ring=key_ring,
        secret_generator=SystemSecretGenerator(),
    )
    account_id = _seed_active_account(migrated_engine, email_protector)
    sender = _RecordingEmailSender()
    operations = _test_operations(migrated_engine, sender)
    start = threading.Barrier(2)

    def submit_request() -> bool | None:
        start.wait(timeout=5)
        return operations.request(email=ACTIVE_EMAIL)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: submit_request(), range(2)))

    rows = _link_rows(migrated_engine, account_id)
    assert outcomes == [True, True]
    assert len(sender.notifications) == 2
    assert len(rows) == 2
    assert sum(row.status == "active" for row in rows) == 1
    assert sorted(row.status for row in rows) == ["active", "invalidated"]


def test_t058_postgres_resolves_only_current_active_claim_without_issuing_link(
    migrated_engine: Engine,
) -> None:
    protector = AdministrativeEmailProtector(
        key_ring=CryptographyKeyRing(load_cryptography_key_configuration()),
        secret_generator=SystemSecretGenerator(),
    )
    active_email = protector.protect("synthetic.active@example.test")
    reserved_email = protector.protect("synthetic.reserved@example.test")
    pending_email = protector.protect("synthetic.pending@example.test")
    with migrated_engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount)
            .values(
                role="owner",
                status="active",
                password_hash=AdministrativePasswordHasher().hash_password("synthetic password"),
            )
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        for kind, protected in (("current", active_email), ("reserved", reserved_email)):
            connection.execute(
                insert(AdminEmailClaim).values(
                    admin_account_id=account_id,
                    claim_kind=kind,
                    lookup_digest=protected.lookup_digest,
                    email_ciphertext=protected.email_ciphertext,
                    key_version=protected.key_version,
                )
            )
        pending_account_id = connection.execute(
            insert(AdminAccount)
            .values(role="staff", status="pending")
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=pending_account_id,
                claim_kind="current",
                lookup_digest=pending_email.lookup_digest,
                email_ciphertext=pending_email.email_ciphertext,
                key_version=pending_email.key_version,
            )
        )

    with migrated_engine.begin() as connection:
        requester = RequestAdministrativePasswordRecovery(
            store=PostgresAdministrativeRecoveryAccountStore(connection),
            email_lookup=protector,
        )
        assert requester.request(email=" SYNTHETIC.ACTIVE@EXAMPLE.TEST ") == PasswordRecoveryIntent(account_id)
        assert requester.request(email="synthetic.reserved@example.test") is None
        assert requester.request(email="synthetic.absent@example.test") is None
        assert requester.request(email="synthetic.pending@example.test") is None
        app = FastAPI()
        app.include_router(router)
        register_administrative_security_headers(app)
        app.dependency_overrides[get_password_recovery_operations] = lambda: requester
        with TestClient(app) as client:
            responses = [
                client.post("/api/admin/password-recovery", json={"email": email})
                for email in (
                    "synthetic.active@example.test",
                    "synthetic.pending@example.test",
                    "synthetic.absent@example.test",
                )
            ]
        assert all(response.status_code == 202 for response in responses)
        assert all(
            (response.content, dict(response.headers))
            == (responses[0].content, dict(responses[0].headers))
            for response in responses
        )
        assert connection.execute(select(SecurityLink.security_link_id)).all() == []
