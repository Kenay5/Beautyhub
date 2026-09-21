"""T012 PostgreSQL evidence for factor and one-time credential persistence."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
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


def _insert_account(connection: Connection, *, role: str, status: str) -> int:
    return connection.execute(
        text(
            "INSERT INTO admin_accounts (role, status) "
            "VALUES (:role, :status) RETURNING admin_account_id"
        ),
        {"role": role, "status": status},
    ).scalar_one()


def _insert_active_factor(connection: Connection, *, account_id: int, marker: int) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO totp_factors (
                admin_account_id, totp_secret_ciphertext, key_version, algorithm,
                digits, period_seconds, status, confirmed_at, invalidated_at
            ) VALUES (
                :account_id, :ciphertext, 'v1', 'SHA1', 6, 30, 'active',
                :confirmed_at, NULL
            ) RETURNING totp_factor_id
            """
        ),
        {
            "account_id": account_id,
            "ciphertext": bytes([marker]) * 32,
            "confirmed_at": datetime(2030, 6, 15, 10, tzinfo=timezone.utc),
        },
    ).scalar_one()


@pytest.mark.integration
def test_t012_persists_protected_factors_and_one_time_credentials(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert {"totp_factors", "totp_period_uses", "recovery_codes"}.issubset(
        inspector.get_table_names()
    )
    assert "totp_secret" not in {
        column["name"] for column in inspector.get_columns("totp_factors")
    }
    assert "recovery_code" not in {
        column["name"] for column in inspector.get_columns("recovery_codes")
    }

    instant = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            account_id = _insert_account(
                connection, role="owner", status="inactive"
            )
            other_account_id = _insert_account(
                connection, role="staff", status="deactivated"
            )
            factor_id = _insert_active_factor(
                connection, account_id=account_id, marker=1
            )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_active_factor(
                        connection, account_id=account_id, marker=2
                    )

            connection.execute(
                text(
                    "UPDATE totp_factors SET status = 'invalidated', "
                    "totp_secret_ciphertext = NULL, key_version = NULL, "
                    "invalidated_at = :invalidated_at "
                    "WHERE totp_factor_id = :factor_id"
                ),
                {"factor_id": factor_id, "invalidated_at": instant},
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE totp_factors SET status = 'active', "
                            "totp_secret_ciphertext = :ciphertext, key_version = 'v1', "
                            "invalidated_at = NULL WHERE totp_factor_id = :factor_id"
                        ),
                        {"factor_id": factor_id, "ciphertext": b"\x03" * 32},
                    )
            current_factor_id = _insert_active_factor(
                connection, account_id=account_id, marker=4
            )

            connection.execute(
                text(
                    "INSERT INTO totp_period_uses ("
                    "admin_account_id, totp_factor_id, period_counter, consumed_at"
                    ") VALUES (:account_id, :factor_id, 12345, :consumed_at)"
                ),
                {
                    "account_id": account_id,
                    "factor_id": current_factor_id,
                    "consumed_at": instant,
                },
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO totp_period_uses ("
                            "admin_account_id, totp_factor_id, period_counter, consumed_at"
                            ") VALUES (:account_id, :factor_id, 12345, :consumed_at)"
                        ),
                        {
                            "account_id": account_id,
                            "factor_id": current_factor_id,
                            "consumed_at": instant,
                        },
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO totp_period_uses ("
                            "admin_account_id, totp_factor_id, period_counter, consumed_at"
                            ") VALUES (:account_id, :factor_id, 12346, :consumed_at)"
                        ),
                        {
                            "account_id": other_account_id,
                            "factor_id": current_factor_id,
                            "consumed_at": instant,
                        },
                    )

            recovery_id = connection.execute(
                text(
                    """
                    INSERT INTO recovery_codes (
                        admin_account_id, lookup_digest, key_version, position,
                        status, used_at, invalidated_at
                    ) VALUES (
                        :account_id, :digest, 'v1', 1, 'active', NULL, NULL
                    ) RETURNING recovery_code_id
                    """
                ),
                {"account_id": account_id, "digest": b"\x05" * 32},
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE recovery_codes SET status = 'used', used_at = :used_at "
                    "WHERE recovery_code_id = :recovery_id"
                ),
                {"recovery_id": recovery_id, "used_at": instant},
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE recovery_codes SET status = 'active', used_at = NULL "
                            "WHERE recovery_code_id = :recovery_id"
                        ),
                        {"recovery_id": recovery_id},
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO recovery_codes ("
                            "admin_account_id, lookup_digest, key_version, position, "
                            "status, used_at, invalidated_at"
                            ") VALUES (:account_id, :digest, 'v1', 2, 'active', NULL, NULL)"
                        ),
                        {"account_id": account_id, "digest": b"\x05" * 32},
                    )
        finally:
            transaction.rollback()
