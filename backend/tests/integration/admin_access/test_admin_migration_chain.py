"""T019 PostgreSQL evidence for the complete administrative migration chain."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SPEC001_HEAD = "20260914_10"
ADMIN_HEAD = "head"
FIXTURE_TIME = datetime(2032, 1, 10, 15, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        yield engine
    finally:
        _upgrade_to_head(engine)
        engine.dispose()


@pytest.mark.integration
def test_t019_migrations_round_trip_from_empty_and_preserve_spec001_appointments(
    postgres_engine: Engine,
) -> None:
    """Exercise the chain only against the dedicated PostgreSQL test database."""
    fixture_ids: tuple[int, int, int] | None = None
    try:
        _downgrade(postgres_engine, "base")
        with postgres_engine.connect() as connection:
            assert "appointments" not in inspect(connection).get_table_names()

        _upgrade_to_head(postgres_engine)
        with postgres_engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
        assert {"appointments", "admin_accounts", "security_links"} <= table_names

        _downgrade(postgres_engine, SPEC001_HEAD)
        fixture_ids = _insert_spec001_appointment_fixture(postgres_engine)
        before_upgrade = _read_appointment_fixture(postgres_engine, fixture_ids[2])

        _upgrade_to_head(postgres_engine)
        assert _read_appointment_fixture(postgres_engine, fixture_ids[2]) == before_upgrade

        _downgrade(postgres_engine, SPEC001_HEAD)
        with postgres_engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
        assert "admin_accounts" not in table_names
        assert _read_appointment_fixture(postgres_engine, fixture_ids[2]) == before_upgrade
    finally:
        _upgrade_to_head(postgres_engine)
        if fixture_ids is not None:
            _delete_spec001_appointment_fixture(postgres_engine, fixture_ids)


@pytest.mark.integration
def test_t019_alembic_keeps_existing_application_loggers_enabled(
    postgres_engine: Engine,
) -> None:
    application_logger = logging.getLogger("beautyhub.security")
    previous_disabled = application_logger.disabled
    application_logger.disabled = False
    try:
        _upgrade_to_head(postgres_engine)
        assert application_logger.disabled is False
    finally:
        application_logger.disabled = previous_disabled


@pytest.mark.integration
def test_t085_security_migration_downgrade_fails_closed(
    postgres_engine: Engine,
) -> None:
    _upgrade_to_head(postgres_engine)
    _downgrade(postgres_engine, "20260926_28")
    try:
        with postgres_engine.connect() as connection:
            transaction = connection.begin()
            try:
                event_id = connection.execute(
                    text(
                        "INSERT INTO admin_audit_events (action, result, occurred_at) "
                        "VALUES ('login', 'failed', :occurred_at) "
                        "RETURNING admin_audit_event_id"
                    ),
                    {"occurred_at": FIXTURE_TIME},
                ).scalar_one()
                connection.execute(
                    text(
                        "SELECT set_config("
                        "'beautyhub.administrative_history_retention_delete', "
                        "'authorized', true)"
                    )
                )
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                "DELETE FROM admin_audit_events "
                                "WHERE admin_audit_event_id = :event_id "
                                "/* purge_expired_administrative_history_event_batch */"
                            ),
                            {"event_id": event_id},
                        )
            finally:
                transaction.rollback()
    finally:
        _upgrade_to_head(postgres_engine)


def _alembic_config(connection: Connection) -> Config:
    config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def _downgrade(engine: Engine, revision: str) -> None:
    with engine.connect() as connection:
        command.downgrade(_alembic_config(connection), revision)


def _upgrade_to_head(engine: Engine) -> None:
    with engine.connect() as connection:
        command.upgrade(_alembic_config(connection), ADMIN_HEAD)


def _insert_spec001_appointment_fixture(engine: Engine) -> tuple[int, int, int]:
    with engine.begin() as connection:
        service_id = connection.execute(
            text(
                """
                INSERT INTO services (
                    name, description, duration_minutes, price, is_active,
                    available_chiconcuac, available_texcoco
                ) VALUES (
                    'T019 fixture service', 'Fictitious migration fixture', 30, 250.00,
                    TRUE, TRUE, FALSE
                ) RETURNING service_id
                """
            )
        ).scalar_one()
        privacy_notice_version_id = connection.execute(
            text(
                """
                INSERT INTO privacy_notice_versions (
                    version, content, published_at, valid_from, valid_until
                ) VALUES (
                    't019-fixture-v1', 'Fictitious privacy notice fixture',
                    :fixture_time, :fixture_time, NULL
                ) RETURNING privacy_notice_version_id
                """
            ),
            {"fixture_time": FIXTURE_TIME},
        ).scalar_one()
        appointment_id = connection.execute(
            text(
                """
                INSERT INTO appointments (
                    private_code_ciphertext, private_code_digest, first_name, last_name,
                    phone, email, service_id, service_snapshot_name,
                    service_snapshot_duration_minutes, service_snapshot_price, branch,
                    scheduled_start, scheduled_end, status, cancellation_reason, origin,
                    created_by_account_id, privacy_notice_version_id,
                    privacy_notice_accepted_at, contact_processing_authorized,
                    adult_responsibility_declared
                ) VALUES (
                    :ciphertext, :digest, 'Fixture', 'Record', '5550000000',
                    'fixture@example.invalid', :service_id, 'T019 fixture service',
                    30, 250.00, 'texcoco', :scheduled_start, :scheduled_end,
                    'scheduled', NULL, 'public', NULL, :privacy_notice_version_id,
                    :fixture_time, TRUE, TRUE
                ) RETURNING appointment_id
                """
            ),
            {
                "ciphertext": b"t019-fixture-ciphertext",
                "digest": b"\x19" * 32,
                "service_id": service_id,
                "privacy_notice_version_id": privacy_notice_version_id,
                "fixture_time": FIXTURE_TIME,
                "scheduled_start": FIXTURE_TIME + timedelta(days=7),
                "scheduled_end": FIXTURE_TIME + timedelta(days=7, minutes=30),
            },
        ).scalar_one()
    return service_id, privacy_notice_version_id, appointment_id


def _read_appointment_fixture(engine: Engine, appointment_id: int) -> tuple[object, ...]:
    with engine.connect() as connection:
        return connection.execute(
            text(
                """
                SELECT
                    private_code_ciphertext, private_code_digest, service_id,
                    service_snapshot_name, service_snapshot_duration_minutes,
                    service_snapshot_price, branch, scheduled_start, scheduled_end,
                    status, origin, privacy_notice_version_id,
                    privacy_notice_accepted_at, contact_processing_authorized,
                    adult_responsibility_declared
                FROM appointments
                WHERE appointment_id = :appointment_id
                """
            ),
            {"appointment_id": appointment_id},
        ).one()


def _delete_spec001_appointment_fixture(
    engine: Engine, fixture_ids: tuple[int, int, int]
) -> None:
    service_id, privacy_notice_version_id, appointment_id = fixture_ids
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM appointments WHERE appointment_id = :appointment_id"),
            {"appointment_id": appointment_id},
        )
        connection.execute(
            text(
                "DELETE FROM privacy_notice_versions "
                "WHERE privacy_notice_version_id = :privacy_notice_version_id"
            ),
            {"privacy_notice_version_id": privacy_notice_version_id},
        )
        connection.execute(
            text("DELETE FROM services WHERE service_id = :service_id"),
            {"service_id": service_id},
        )
