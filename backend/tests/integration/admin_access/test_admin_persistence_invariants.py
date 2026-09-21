"""T018 PostgreSQL evidence for administrative persistence invariants."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    SecurityNotificationDelivery,
)
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            alembic_config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")
        yield engine
    finally:
        engine.dispose()


ADMIN_TABLES = (
    "admin_accounts",
    "owner_bootstrap_state",
    "admin_email_claims",
    "security_links",
    "pending_security_setups",
    "totp_factors",
    "totp_period_uses",
    "recovery_codes",
    "admin_sessions",
    "admin_credential_failure_events",
    "admin_account_security_states",
    "rate_limit_events",
    "rate_limit_guards",
    "admin_audit_events",
    "security_notification_deliveries",
)


@pytest.mark.integration
def test_t018_administrative_schema_excludes_prohibited_plaintext_fields(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    prohibited = {
        "password",
        "email",
        "ip_address",
        "token",
        "totp_code",
        "recovery_code",
        "private_code",
        "first_name",
        "last_name",
        "phone",
        "client_name",
        "provider_error",
        "complete_link",
    }
    actual_columns = {
        column["name"]
        for table_name in ADMIN_TABLES
        for column in inspector.get_columns(table_name)
    }

    assert not prohibited & actual_columns


@pytest.mark.integration
def test_t018_rejects_invalid_states_broken_relations_and_audit_updates(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "INSERT INTO admin_accounts (role, status) "
                    "VALUES ('owner', 'inactive')"
                )
            )
            _assert_rejected(
                connection,
                "INSERT INTO admin_accounts (role, status) "
                "VALUES ('owner', 'active')",
            )
            connection.execute(
                text(
                    "INSERT INTO admin_accounts (role, status) "
                    "VALUES ('staff', 'pending')"
                )
            )
            _assert_rejected(
                connection,
                "INSERT INTO admin_accounts (role, status) "
                "VALUES ('staff', 'active')",
            )
            account_id = _insert_deactivated_staff(connection)

            _assert_rejected(
                connection,
                "INSERT INTO admin_accounts (role, status) "
                "VALUES ('owner', 'pending')",
            )
            _assert_rejected(
                connection,
                "UPDATE admin_accounts SET role = 'owner' "
                "WHERE admin_account_id = :account_id",
                {"account_id": account_id},
            )
            _assert_rejected(
                connection,
                "UPDATE admin_accounts SET status = 'active' "
                "WHERE admin_account_id = :account_id",
                {"account_id": account_id},
            )
            _assert_rejected(
                connection,
                "INSERT INTO admin_email_claims ("
                "admin_account_id, claim_kind, lookup_digest, email_ciphertext, key_version"
                ") VALUES (9223372036854775807, 'current', :digest, :ciphertext, 'v1')",
                {"digest": b"\x11" * 32, "ciphertext": b"protected"},
            )

            link_id = connection.execute(
                text(
                    "INSERT INTO security_links ("
                    "admin_account_id, purpose, token_digest, key_version, issued_at, "
                    "expires_at, status, delivery_status, consumed_at, invalidated_at"
                    ") VALUES ("
                    ":account_id, 'invitation', :digest, 'v1', :issued_at, :expires_at, "
                    "'active', 'pending', NULL, NULL"
                    ") RETURNING security_link_id"
                ),
                {
                    "account_id": account_id,
                    "digest": b"\x12" * 32,
                    "issued_at": NOW,
                    "expires_at": NOW + timedelta(hours=24),
                },
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE security_links SET status = 'invalidated', "
                    "delivery_status = 'failed', invalidated_at = :changed_at "
                    "WHERE security_link_id = :link_id"
                ),
                {"changed_at": NOW + timedelta(minutes=1), "link_id": link_id},
            )
            _assert_rejected(
                connection,
                "UPDATE security_links SET status = 'active', "
                "delivery_status = 'pending', invalidated_at = NULL "
                "WHERE security_link_id = :link_id",
                {"link_id": link_id},
            )

            setup_id = connection.execute(
                text(
                    "INSERT INTO pending_security_setups ("
                    "admin_account_id, flow, status, totp_secret_ciphertext, key_version, "
                    "created_at, expires_at"
                    ") VALUES ("
                    ":account_id, 'staff_activation', 'pending', :ciphertext, 'v1', "
                    ":created_at, :expires_at"
                    ") RETURNING pending_security_setup_id"
                ),
                {
                    "account_id": account_id,
                    "ciphertext": b"protected-totp",
                    "created_at": NOW,
                    "expires_at": NOW + timedelta(minutes=30),
                },
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE pending_security_setups SET status = 'expired', "
                    "totp_secret_ciphertext = NULL, key_version = NULL "
                    "WHERE pending_security_setup_id = :setup_id"
                ),
                {"setup_id": setup_id},
            )
            _assert_rejected(
                connection,
                "UPDATE pending_security_setups SET status = 'pending', "
                "totp_secret_ciphertext = :ciphertext, key_version = 'v1' "
                "WHERE pending_security_setup_id = :setup_id",
                {"ciphertext": b"new-protected-totp", "setup_id": setup_id},
            )

            delivery_id = connection.execute(
                text(
                    "INSERT INTO security_notification_deliveries ("
                    "event, recipient_ciphertext, recipient_key_version, template, "
                    "idempotency_key_digest, status, sanitized_error"
                    ") VALUES ("
                    "'password_changed', :ciphertext, 'v1', 'password_changed_notice', "
                    ":digest, 'pending', NULL"
                    ") RETURNING security_notification_delivery_id"
                ),
                {"ciphertext": b"protected-email", "digest": b"\x13" * 32},
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE security_notification_deliveries SET status = 'accepted' "
                    "WHERE security_notification_delivery_id = :delivery_id"
                ),
                {"delivery_id": delivery_id},
            )
            _assert_rejected(
                connection,
                "UPDATE security_notification_deliveries SET status = 'pending' "
                "WHERE security_notification_delivery_id = :delivery_id",
                {"delivery_id": delivery_id},
            )

            audit_id = connection.execute(
                text(
                    "INSERT INTO admin_audit_events ("
                    "actor_account_id, action, result, occurred_at, target_reference"
                    ") VALUES (NULL, 'login', 'failed', :occurred_at, NULL) "
                    "RETURNING admin_audit_event_id"
                ),
                {"occurred_at": NOW},
            ).scalar_one()
            _assert_rejected(
                connection,
                "UPDATE admin_audit_events SET result = 'succeeded' "
                "WHERE admin_audit_event_id = :audit_id",
                {"audit_id": audit_id},
            )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_t018_concurrent_email_claims_allow_only_one_duplicate_digest(
    migrated_engine: Engine,
) -> None:
    account_ids = _create_deactivated_staff_accounts(migrated_engine, 2)
    digest = b"\x21" * 32
    try:
        outcomes = _run_concurrently(
            tuple(
                lambda account_id=account_id: _attempt_email_claim(
                    migrated_engine, account_id, digest
                )
                for account_id in account_ids
            )
        )
        assert sorted(outcomes) == ["accepted", "rejected"]
        with migrated_engine.connect() as connection:
            count = connection.execute(
                select(func.count())
                .select_from(AdminEmailClaim)
                .where(AdminEmailClaim.lookup_digest == digest)
            ).scalar_one()
        assert count == 1
    finally:
        _delete_accounts(migrated_engine, account_ids)


@pytest.mark.integration
def test_t018_concurrent_security_deliveries_reject_a_duplicate_intent(
    migrated_engine: Engine,
) -> None:
    digest = b"\x22" * 32
    try:
        outcomes = _run_concurrently(
            (
                lambda: _attempt_security_delivery(migrated_engine, digest, b"first"),
                lambda: _attempt_security_delivery(migrated_engine, digest, b"second"),
            )
        )
        assert sorted(outcomes) == ["accepted", "rejected"]
        with migrated_engine.connect() as connection:
            count = connection.execute(
                select(func.count())
                .select_from(SecurityNotificationDelivery)
                .where(SecurityNotificationDelivery.idempotency_key_digest == digest)
            ).scalar_one()
        assert count == 1
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(
                SecurityNotificationDelivery.__table__.delete().where(
                    SecurityNotificationDelivery.idempotency_key_digest == digest
                )
            )


def _insert_deactivated_staff(connection: Connection) -> int:
    return connection.execute(
        text(
            "INSERT INTO admin_accounts (role, status) "
            "VALUES ('staff', 'deactivated') RETURNING admin_account_id"
        )
    ).scalar_one()


def _assert_rejected(
    connection: Connection,
    statement: str,
    parameters: dict[str, object] | None = None,
) -> None:
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.execute(text(statement), parameters or {})


def _run_concurrently(workers: tuple[Callable[[], str], ...]) -> list[str]:
    barrier = Barrier(len(workers))

    def synchronized(worker: Callable[[], str]) -> str:
        barrier.wait(timeout=10)
        return worker()

    with ThreadPoolExecutor(max_workers=len(workers)) as executor:
        return list(executor.map(synchronized, workers))


def _create_deactivated_staff_accounts(engine: Engine, count: int) -> tuple[int, ...]:
    with engine.begin() as connection:
        return tuple(_insert_deactivated_staff(connection) for _ in range(count))


def _attempt_email_claim(engine: Engine, account_id: int, digest: bytes) -> str:
    try:
        with engine.begin() as connection:
            connection.execute(
                AdminEmailClaim.__table__.insert().values(
                    admin_account_id=account_id,
                    claim_kind="current",
                    lookup_digest=digest,
                    email_ciphertext=b"protected-email",
                    key_version="v1",
                )
            )
        return "accepted"
    except DBAPIError:
        return "rejected"


def _attempt_security_delivery(
    engine: Engine, digest: bytes, marker: bytes
) -> str:
    try:
        with engine.begin() as connection:
            connection.execute(
                SecurityNotificationDelivery.__table__.insert().values(
                    event="password_changed",
                    recipient_ciphertext=b"protected-" + marker,
                    recipient_key_version="v1",
                    template="password_changed_notice",
                    idempotency_key_digest=digest,
                    status="pending",
                    sanitized_error=None,
                )
            )
        return "accepted"
    except DBAPIError:
        return "rejected"


def _delete_accounts(engine: Engine, account_ids: tuple[int, ...]) -> None:
    with engine.begin() as connection:
        connection.execute(
            AdminAccount.__table__.delete().where(
                AdminAccount.admin_account_id.in_(account_ids)
            )
        )
