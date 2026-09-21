"""T013 PostgreSQL evidence for one opaque active administrative session."""

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


def _insert_owner(connection: Connection) -> int:
    return connection.execute(
        text(
            "INSERT INTO admin_accounts (role, status) "
            "VALUES ('owner', 'inactive') RETURNING admin_account_id"
        )
    ).scalar_one()


def _insert_active_session(
    connection: Connection, *, account_id: int, marker: int
) -> int:
    created_at = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    return connection.execute(
        text(
            """
            INSERT INTO admin_sessions (
                admin_account_id, session_digest, csrf_digest, key_version,
                created_at, last_human_activity_at, absolute_expires_at,
                status, invalidated_at
            ) VALUES (
                :account_id, :session_digest, :csrf_digest, 'v1',
                :created_at, :last_human_activity_at, :absolute_expires_at,
                'active', NULL
            ) RETURNING admin_session_id
            """
        ),
        {
            "account_id": account_id,
            "session_digest": bytes([marker]) * 32,
            "csrf_digest": bytes([marker + 10]) * 32,
            "created_at": created_at,
            "last_human_activity_at": created_at,
            "absolute_expires_at": created_at + timedelta(hours=8),
        },
    ).scalar_one()


@pytest.mark.integration
def test_t013_persists_only_opaque_one_active_session_per_account(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert "admin_sessions" in inspector.get_table_names()
    column_names = {
        column["name"] for column in inspector.get_columns("admin_sessions")
    }
    assert "session_token" not in column_names
    assert "csrf_token" not in column_names

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            account_id = _insert_owner(connection)
            session_id = _insert_active_session(
                connection, account_id=account_id, marker=1
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_active_session(
                        connection, account_id=account_id, marker=2
                    )

            invalidated_at = datetime(2030, 6, 15, 10, 5, tzinfo=timezone.utc)
            connection.execute(
                text(
                    "UPDATE admin_sessions SET status = 'invalidated', "
                    "invalidated_at = :invalidated_at "
                    "WHERE admin_session_id = :session_id"
                ),
                {"session_id": session_id, "invalidated_at": invalidated_at},
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE admin_sessions SET status = 'active', "
                            "invalidated_at = NULL WHERE admin_session_id = :session_id"
                        ),
                        {"session_id": session_id},
                    )
            _insert_active_session(connection, account_id=account_id, marker=3)

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    created_at = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
                    connection.execute(
                        text(
                            """
                            INSERT INTO admin_sessions (
                                admin_account_id, session_digest, csrf_digest,
                                key_version, created_at, last_human_activity_at,
                                absolute_expires_at, status, invalidated_at
                            ) VALUES (
                                :account_id, :session_digest, :csrf_digest,
                                'v1', :created_at, :created_at,
                                :absolute_expires_at, 'invalidated', :invalidated_at
                            )
                            """
                        ),
                        {
                            "account_id": account_id,
                            "session_digest": b"short",
                            "csrf_digest": b"\x09" * 32,
                            "created_at": created_at,
                            "absolute_expires_at": created_at + timedelta(hours=7),
                            "invalidated_at": created_at,
                        },
                    )
        finally:
            transaction.rollback()
