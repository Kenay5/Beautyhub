"""T010 PostgreSQL evidence for protected administrative email claim storage."""

from __future__ import annotations

from collections.abc import Iterator
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
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE admin_accounts, owner_bootstrap_state "
                    "RESTART IDENTITY CASCADE"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO owner_bootstrap_state "
                    "(bootstrap_state_id, status) VALUES (1, 'open')"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _insert_account(connection: Connection, *, role: str, status: str) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO admin_accounts (role, status)
            VALUES (:role, :status)
            RETURNING admin_account_id
            """
        ),
        {"role": role, "status": status},
    ).scalar_one()


def _insert_claim(
    connection: Connection,
    *,
    account_id: int,
    kind: str,
    digest_marker: int,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO admin_email_claims (
                admin_account_id, claim_kind, lookup_digest, email_ciphertext,
                key_version
            ) VALUES (
                :account_id, :claim_kind, :lookup_digest, :email_ciphertext,
                :key_version
            )
            """
        ),
        {
            "account_id": account_id,
            "claim_kind": kind,
            "lookup_digest": bytes([digest_marker]) * 32,
            "email_ciphertext": b"synthetic-admin-email-ciphertext",
            "key_version": "v1",
        },
    )


@pytest.mark.integration
def test_t010_persists_only_protected_unique_current_and_reserved_claims(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)

    assert "admin_email_claims" in inspector.get_table_names()
    assert {
        column["name"] for column in inspector.get_columns("admin_email_claims")
    } == {
        "admin_email_claim_id",
        "admin_account_id",
        "claim_kind",
        "lookup_digest",
        "email_ciphertext",
        "key_version",
        "created_at",
        "updated_at",
    }

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            owner_id = _insert_account(connection, role="owner", status="inactive")
            staff_id = _insert_account(connection, role="staff", status="deactivated")
            _insert_claim(
                connection,
                account_id=owner_id,
                kind="current",
                digest_marker=1,
            )
            _insert_claim(
                connection,
                account_id=owner_id,
                kind="reserved",
                digest_marker=2,
            )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_claim(
                        connection,
                        account_id=staff_id,
                        kind="current",
                        digest_marker=1,
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_claim(
                        connection,
                        account_id=owner_id,
                        kind="current",
                        digest_marker=3,
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_claim(
                        connection,
                        account_id=owner_id,
                        kind="reserved",
                        digest_marker=4,
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            INSERT INTO admin_email_claims (
                                admin_account_id, claim_kind, lookup_digest,
                                email_ciphertext, key_version
                            ) VALUES (:account_id, 'current', :digest, :ciphertext, 'v1')
                            """
                        ),
                        {
                            "account_id": staff_id,
                            "digest": b"short",
                            "ciphertext": b"synthetic-admin-email-ciphertext",
                        },
                    )
        finally:
            transaction.rollback()
