"""T009 PostgreSQL evidence for administrative account persistence invariants."""

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


@pytest.mark.integration
def test_t009_persists_singleton_bootstrap_and_account_cardinality(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)

    assert {"admin_accounts", "owner_bootstrap_state"}.issubset(
        inspector.get_table_names()
    )
    assert {
        column["name"] for column in inspector.get_columns("admin_accounts")
    } == {
        "admin_account_id",
        "role",
        "status",
        "password_hash",
        "created_at",
        "updated_at",
    }

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            assert connection.execute(
                text(
                    "SELECT bootstrap_state_id, status, owner_account_id, closed_at "
                    "FROM owner_bootstrap_state"
                )
            ).one()._tuple() == (1, "open", None, None)

            owner_id = _insert_account(
                connection, role="owner", status="inactive"
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_account(connection, role="owner", status="inactive")

            pending_staff_id = _insert_account(
                connection, role="staff", status="pending"
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_account(connection, role="staff", status="active")

            connection.execute(
                text(
                    "UPDATE admin_accounts SET status = 'deactivated' "
                    "WHERE admin_account_id = :account_id"
                ),
                {"account_id": pending_staff_id},
            )
            replacement_staff_id = _insert_account(
                connection, role="staff", status="active"
            )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE owner_bootstrap_state "
                            "SET status = 'closed', owner_account_id = :account_id, "
                            "closed_at = now()"
                        ),
                        {"account_id": replacement_staff_id},
                    )

            connection.execute(
                text(
                    "UPDATE owner_bootstrap_state "
                    "SET status = 'closed', owner_account_id = :account_id, "
                    "closed_at = now()"
                ),
                {"account_id": owner_id},
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE owner_bootstrap_state "
                            "SET status = 'open', closed_at = NULL"
                        )
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(text("DELETE FROM owner_bootstrap_state"))
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE admin_accounts SET role = 'staff' "
                            "WHERE admin_account_id = :account_id"
                        ),
                        {"account_id": owner_id},
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "DELETE FROM admin_accounts "
                            "WHERE admin_account_id = :account_id"
                        ),
                        {"account_id": owner_id},
                    )
        finally:
            transaction.rollback()
