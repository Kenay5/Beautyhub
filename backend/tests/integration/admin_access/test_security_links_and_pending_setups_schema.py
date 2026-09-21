"""T011 PostgreSQL evidence for links and pending security setups."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


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


def _insert_account(connection: Connection) -> int:
    return connection.execute(
        text(
            "INSERT INTO admin_accounts (role, status) "
            "VALUES ('owner', 'inactive') RETURNING admin_account_id"
        )
    ).scalar_one()


def _insert_link(
    connection: Connection,
    *,
    account_id: int,
    purpose: str,
    marker: int,
    status: str = "active",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    delivery_status: str = "pending",
    invalidated_at: datetime | None = None,
) -> None:
    issued = issued_at or datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    expires = expires_at or issued + timedelta(minutes=30)
    connection.execute(
        text(
            """
            INSERT INTO security_links (
                admin_account_id, purpose, token_digest, key_version,
                issued_at, expires_at, status, delivery_status,
                consumed_at, invalidated_at
            ) VALUES (
                :account_id, :purpose, :digest, 'v1', :issued_at, :expires_at,
                :status, :delivery_status, NULL, :invalidated_at
            )
            """
        ),
        {
            "account_id": account_id,
            "purpose": purpose,
            "digest": bytes([marker]) * 32,
            "issued_at": issued,
            "expires_at": expires,
            "status": status,
            "delivery_status": delivery_status,
            "invalidated_at": invalidated_at,
        },
    )


@pytest.mark.integration
def test_t011_persists_expiring_links_with_one_active_per_account_and_purpose(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert {"security_links", "pending_security_setups"}.issubset(
        inspector.get_table_names()
    )
    assert "token" not in {
        column["name"] for column in inspector.get_columns("security_links")
    }
    assert "totp_secret" not in {
        column["name"] for column in inspector.get_columns("pending_security_setups")
    }

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            account_id = _insert_account(connection)
            issued = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
            expires = issued + timedelta(minutes=30)
            _insert_link(
                connection,
                account_id=account_id,
                purpose="invitation",
                marker=1,
                issued_at=issued,
                expires_at=expires,
            )
            _insert_link(
                connection,
                account_id=account_id,
                purpose="password_recovery",
                marker=2,
                issued_at=issued,
                expires_at=expires,
            )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_link(
                        connection,
                        account_id=account_id,
                        purpose="invitation",
                        marker=3,
                        issued_at=issued,
                        expires_at=expires,
                    )

            connection.execute(
                text(
                    "UPDATE security_links SET status = 'invalidated', "
                    "invalidated_at = :invalidated_at WHERE token_digest = :digest"
                ),
                {
                    "invalidated_at": issued + timedelta(minutes=1),
                    "digest": bytes([1]) * 32,
                },
            )
            _insert_link(
                connection,
                account_id=account_id,
                purpose="invitation",
                marker=3,
                issued_at=issued,
                expires_at=expires,
            )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO security_links ("
                            "admin_account_id, purpose, token_digest, key_version, "
                            "issued_at, expires_at, status, delivery_status"
                            ") VALUES (:account_id, 'invitation', :digest, 'v1', "
                            ":issued_at, :expires_at, 'active', 'pending')"
                        ),
                        {
                            "account_id": account_id,
                            "digest": b"short",
                            "issued_at": issued,
                            "expires_at": expires,
                        },
                    )

            connection.execute(
                text(
                    """
                    INSERT INTO pending_security_setups (
                        admin_account_id, flow, status, totp_secret_ciphertext,
                        key_version, created_at, expires_at
                    ) VALUES (
                        :account_id, 'owner_activation', 'pending',
                        :ciphertext, 'v1', :created_at, :expires_at
                    )
                    """
                ),
                {
                    "account_id": account_id,
                    "ciphertext": b"synthetic-encrypted-totp",
                    "created_at": issued,
                    "expires_at": expires,
                },
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            INSERT INTO pending_security_setups (
                                admin_account_id, flow, status,
                                totp_secret_ciphertext, key_version,
                                created_at, expires_at
                            ) VALUES (
                                :account_id, 'owner_activation', 'pending',
                                :ciphertext, 'v1', :created_at, :expires_at
                            )
                            """
                        ),
                        {
                            "account_id": account_id,
                            "ciphertext": b"synthetic-encrypted-totp-2",
                            "created_at": issued,
                            "expires_at": expires,
                        },
                    )
                connection.execute(
                    text(
                        "UPDATE pending_security_setups SET status = 'expired', "
                        "totp_secret_ciphertext = NULL, key_version = NULL "
                        "WHERE admin_account_id = :account_id "
                        "AND flow = 'owner_activation' AND status = 'pending'"
                    ),
                    {"account_id": account_id},
                )
        finally:
            transaction.rollback()
