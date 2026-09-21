"""T016 PostgreSQL evidence for minimum administrative audit persistence."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, and_, delete, inspect, or_, select, text
from sqlalchemy.exc import DBAPIError

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.clock import FixedClock
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import AdminAuditEvent
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2043, 6, 15, 10, tzinfo=timezone.utc)


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


def _insert_actor(connection: Connection) -> int:
    return connection.execute(
        text(
            "INSERT INTO admin_accounts (role, status) "
            "VALUES ('staff', 'deactivated') RETURNING admin_account_id"
        )
    ).scalar_one()


@pytest.mark.integration
def test_t016_persists_identified_and_anonymous_minimum_audit_events(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert "admin_audit_events" in inspector.get_table_names()
    column_names = {
        column["name"] for column in inspector.get_columns("admin_audit_events")
    }
    prohibited = {
        "first_name",
        "last_name",
        "phone",
        "email",
        "password",
        "totp_code",
        "recovery_code",
        "token",
        "private_code",
        "ip_address",
    }
    assert not prohibited & column_names

    actor_id: int | None = None
    try:
        with migrated_engine.begin() as connection:
            actor_id = _insert_actor(connection)
            recorder = RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=FixedClock(NOW),
            )
            recorder.record(
                actor_account_id=actor_id,
                action="appointment_modified",
                result="succeeded",
                target_reference="appointment:13",
            )
            recorder.record(
                actor_account_id=None,
                action="login",
                result="failed",
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        AdminAuditEvent.__table__.insert().values(
                            actor_account_id=actor_id,
                            action="appointment_modified",
                            result="succeeded",
                            occurred_at=NOW,
                            target_reference="client@example.test",
                        )
                    )

        with migrated_engine.connect() as connection:
            rows = connection.execute(
                select(
                    AdminAuditEvent.actor_account_id,
                    AdminAuditEvent.action,
                    AdminAuditEvent.result,
                    AdminAuditEvent.occurred_at,
                    AdminAuditEvent.target_reference,
                )
                .where(
                    or_(
                        AdminAuditEvent.actor_account_id == actor_id,
                        and_(
                            AdminAuditEvent.actor_account_id.is_(None),
                            AdminAuditEvent.action == "login",
                            AdminAuditEvent.occurred_at == NOW,
                        ),
                    )
                )
                .order_by(AdminAuditEvent.admin_audit_event_id.desc())
                .limit(2)
            ).all()

        assert {(row.action, row.result) for row in rows} == {
            ("appointment_modified", "succeeded"),
            ("login", "failed"),
        }
        identified = next(row for row in rows if row.actor_account_id == actor_id)
        anonymous = next(row for row in rows if row.actor_account_id is None)
        assert identified.target_reference == "appointment:13"
        assert identified.occurred_at == NOW
        assert anonymous.target_reference is None
        assert anonymous.occurred_at == NOW
    finally:
        if actor_id is not None:
            with migrated_engine.begin() as connection:
                connection.execute(
                    delete(AdminAuditEvent).where(
                        or_(
                            AdminAuditEvent.actor_account_id == actor_id,
                            and_(
                                AdminAuditEvent.actor_account_id.is_(None),
                                AdminAuditEvent.action == "login",
                                AdminAuditEvent.occurred_at == NOW,
                            ),
                        )
                    )
                )
                connection.execute(
                    text(
                        "DELETE FROM admin_accounts WHERE admin_account_id = :actor_id"
                    ),
                    {"actor_id": actor_id},
                )
