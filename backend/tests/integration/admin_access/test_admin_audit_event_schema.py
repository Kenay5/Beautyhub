"""T016 PostgreSQL evidence for minimum administrative audit persistence."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, and_, create_engine, inspect, or_, select, text
from sqlalchemy.engine import make_url
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
    assert column_names == {
        "admin_audit_event_id",
        "actor_account_id",
        "action",
        "result",
        "occurred_at",
        "target_reference",
    }

    actor_id: int | None = None
    connection = migrated_engine.connect()
    transaction = connection.begin()
    try:
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

        rows = connection.execute(
            select(
                AdminAuditEvent.admin_audit_event_id,
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
                    )
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
        for statement in (
            "UPDATE admin_audit_events SET result = 'failed' "
            "WHERE admin_audit_event_id = :event_id",
            "DELETE FROM admin_audit_events "
            "WHERE admin_audit_event_id = :event_id",
        ):
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(statement),
                        {"event_id": rows[0].admin_audit_event_id},
                    )

        # The event and its immutable minimum evidence survive rejected writes.
        preserved = connection.execute(
            select(
                AdminAuditEvent.action,
                AdminAuditEvent.result,
                AdminAuditEvent.target_reference,
            ).where(
                AdminAuditEvent.admin_audit_event_id == rows[0].admin_audit_event_id
            )
        ).one()
        assert preserved == (rows[0].action, rows[0].result, rows[0].target_reference)
    finally:
        transaction.rollback()
        connection.close()


@pytest.mark.integration
def test_t085_spoofed_retention_guc_and_query_comment_cannot_delete_event(
    migrated_engine: Engine,
) -> None:
    connection = migrated_engine.connect()
    transaction = connection.begin()
    try:
        event_id = connection.execute(
            text(
                "INSERT INTO admin_audit_events (action, result, occurred_at) "
                "VALUES ('login', 'succeeded', :occurred_at) "
                "RETURNING admin_audit_event_id"
            ),
            {"occurred_at": NOW},
        ).scalar_one()
        connection.execute(
            text(
                "SELECT set_config("
                "'beautyhub.administrative_history_retention_delete', "
                "'authorized', true)"
            )
        )
        # This is the exact direct DELETE that passed revision 27's trigger.
        with pytest.raises(DBAPIError) as rejected:
            with connection.begin_nested():
                connection.execute(
                    text(
                        "DELETE FROM admin_audit_events "
                        "WHERE admin_audit_event_id = :event_id "
                        "/* purge_expired_administrative_history_event_batch */"
                    ),
                    {"event_id": event_id},
                )
        assert rejected.value.orig.sqlstate == "P0001"
        assert connection.execute(
            text(
                "SELECT admin_audit_event_id FROM admin_audit_events "
                "WHERE admin_audit_event_id = :event_id"
            ),
            {"event_id": event_id},
        ).scalar_one() == event_id
    finally:
        transaction.rollback()
        connection.close()


@pytest.mark.integration
def test_t085_ordinary_sql_role_cannot_mutate_audit_history_or_assume_purge_owner(
    migrated_engine: Engine,
) -> None:
    probe_role = f"t085_probe_{uuid4().hex}"
    probe_password = uuid4().hex
    test_url = make_url(load_test_database_url().reveal())
    event_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with migrated_engine.begin() as connection:
        event_id = connection.execute(
            text(
                "INSERT INTO admin_audit_events (action, result, occurred_at) "
                "VALUES ('login', 'succeeded', :occurred_at) "
                "RETURNING admin_audit_event_id"
            ),
            {"occurred_at": event_time},
        ).scalar_one()
        # Both identifiers and this ephemeral password are generated as hex.
        connection.execute(
            text(f"CREATE ROLE {probe_role} LOGIN PASSWORD '{probe_password}'")
        )
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {probe_role}"))
        connection.execute(
            text(f"GRANT SELECT, INSERT ON admin_audit_events TO {probe_role}")
        )
        connection.execute(
            text(
                "GRANT USAGE ON SEQUENCE "
                f"admin_audit_events_admin_audit_event_id_seq TO {probe_role}"
            )
        )
        connection.execute(
            text(
                "GRANT EXECUTE ON FUNCTION "
                "purge_expired_administrative_history_event_batch(timestamptz, integer) "
                f"TO {probe_role}"
            )
        )
    probe_engine = create_engine(
        test_url.set(username=probe_role, password=probe_password),
        pool_pre_ping=True,
        hide_parameters=True,
    )
    try:
        with probe_engine.begin() as connection:
            assert connection.execute(text("SELECT current_user")).scalar_one() == probe_role
            assert connection.execute(text("SELECT session_user")).scalar_one() == probe_role
            assert connection.execute(
                text(
                    "SELECT admin_audit_event_id FROM admin_audit_events "
                    "WHERE admin_audit_event_id = :event_id"
                ),
                {"event_id": event_id},
            ).scalar_one() == event_id
            connection.execute(
                text(
                    "SELECT set_config("
                    "'beautyhub.administrative_history_retention_delete', "
                    "'authorized', true)"
                )
            )
            statements = (
                "DELETE FROM admin_audit_events WHERE admin_audit_event_id = :event_id "
                "/* purge_expired_administrative_history_event_batch */",
                "WITH purge_expired_administrative_history_event_batch AS "
                "(SELECT 1) DELETE FROM admin_audit_events "
                "WHERE admin_audit_event_id = :event_id",
                "DELETE FROM admin_audit_events WHERE admin_audit_event_id = :event_id",
                "UPDATE admin_audit_events SET result = 'failed' "
                "WHERE admin_audit_event_id = :event_id",
            )
            for statement in statements:
                with pytest.raises(DBAPIError) as rejected:
                    with connection.begin_nested():
                        connection.execute(text(statement), {"event_id": event_id})
                assert rejected.value.orig.sqlstate == "42501"
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(text("SET ROLE beautyhub_audit_retention_owner"))
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("SET SESSION AUTHORIZATION beautyhub_audit_retention_owner")
                    )
            for statement in (
                "ALTER TABLE admin_audit_events DISABLE TRIGGER "
                "trg_admin_audit_events_prevent_delete",
                "TRUNCATE TABLE admin_audit_events",
                "CREATE OR REPLACE FUNCTION prevent_admin_audit_event_delete() "
                "RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RETURN OLD; END; $$",
                "CREATE OR REPLACE FUNCTION prevent_admin_audit_event_update() "
                "RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RETURN NEW; END; $$",
            ):
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        connection.execute(text(statement))
            assert connection.execute(
                text(
                    "SELECT result FROM admin_audit_events "
                    "WHERE admin_audit_event_id = :event_id"
                ),
                {"event_id": event_id},
            ).scalar_one() == "succeeded"
            with connection.begin_nested() as retention_check:
                future_id = connection.execute(
                    text(
                        "INSERT INTO admin_audit_events (action, result, occurred_at) "
                        "VALUES ('login', 'succeeded', :occurred_at) "
                        "RETURNING admin_audit_event_id"
                    ),
                    {"occurred_at": NOW},
                ).scalar_one()
                connection.execute(
                    text(
                        "SELECT purge_expired_administrative_history_event_batch("
                        ":current_time, 500)"
                    ),
                    {"current_time": datetime(9999, 1, 1, tzinfo=timezone.utc)},
                )
                assert connection.execute(
                    text(
                        "SELECT admin_audit_event_id FROM admin_audit_events "
                        "WHERE admin_audit_event_id = :event_id"
                    ),
                    {"event_id": event_id},
                ).scalar_one_or_none() is None
                assert connection.execute(
                    text(
                        "SELECT admin_audit_event_id FROM admin_audit_events "
                        "WHERE admin_audit_event_id = :event_id"
                    ),
                    {"event_id": future_id},
                ).scalar_one() == future_id
                retention_check.rollback()
    finally:
        probe_engine.dispose()
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT purge_expired_administrative_history_event_batch("
                    ":current_time, 500)"
                ),
                {"current_time": datetime.now(timezone.utc)},
            )
            connection.execute(
                text(f"REVOKE SELECT, INSERT ON admin_audit_events FROM {probe_role}")
            )
            connection.execute(
                text(
                    "REVOKE USAGE ON SEQUENCE "
                    f"admin_audit_events_admin_audit_event_id_seq FROM {probe_role}"
                )
            )
            connection.execute(
                text(
                    "REVOKE EXECUTE ON FUNCTION "
                    "purge_expired_administrative_history_event_batch(timestamptz, integer) "
                    f"FROM {probe_role}"
                )
            )
            connection.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {probe_role}"))
            connection.execute(text(f"DROP ROLE {probe_role}"))
