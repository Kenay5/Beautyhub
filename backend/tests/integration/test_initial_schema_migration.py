"""PostgreSQL integration checks for the approved persistence schema."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError, DataError, IntegrityError

from backend.app.application.create_service import CreateService, CreateServiceCommand
from backend.app.application.edit_service import EditService, EditServiceCommand
from backend.app.application.list_active_services import ListActiveServices
from backend.app.application.set_service_status import (
    SetServiceStatus,
    SetServiceStatusCommand,
)
from backend.app.infrastructure.persistence.service_repository import (
    PostgresServiceCreationRepository,
    PostgresServiceEditingRepository,
    PostgresActiveServiceCatalog,
    PostgresServiceStatusRepository,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


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


def valid_service_parameters(**overrides: object) -> dict[str, object]:
    return {
        "name": "Servicio de prueba",
        "description": "Descripción de prueba",
        "duration_minutes": 60,
        "price": Decimal("350.00"),
        "is_active": True,
        "available_chiconcuac": True,
        "available_texcoco": False,
        **overrides,
    }


def insert_service(connection: Connection, values: dict[str, object]) -> None:
    connection.execute(
        text(
            """
            INSERT INTO services (
                name, description, duration_minutes, price, is_active,
                available_chiconcuac, available_texcoco
            ) VALUES (
                :name, :description, :duration_minutes, :price, :is_active,
                :available_chiconcuac, :available_texcoco
            )
            """
        ),
        values,
    )


def create_appointment_dependencies(connection: Connection) -> tuple[int, int]:
    service_id = connection.execute(
        text(
            """
            INSERT INTO services (
                name, description, duration_minutes, price, is_active,
                available_chiconcuac, available_texcoco
            ) VALUES (
                :name, :description, :duration_minutes, :price, :is_active,
                :available_chiconcuac, :available_texcoco
            ) RETURNING service_id
            """
        ),
        valid_service_parameters(name="Servicio para cita"),
    ).scalar_one()
    privacy_notice_version_id = connection.execute(
        text(
            """
            INSERT INTO privacy_notice_versions (
                version, content, published_at, valid_from
            ) VALUES (:version, :content, :published_at, :valid_from)
            RETURNING privacy_notice_version_id
            """
        ),
        {
            "version": "synthetic-appointment-notice-v1",
            "content": "Synthetic appointment notice content",
            "published_at": datetime(2030, 6, 1, tzinfo=timezone.utc),
            "valid_from": datetime(2030, 6, 1, tzinfo=timezone.utc),
        },
    ).scalar_one()
    return service_id, privacy_notice_version_id


def valid_appointment_parameters(
    service_id: int, privacy_notice_version_id: int, **overrides: object
) -> dict[str, object]:
    return {
        "private_code_ciphertext": b"synthetic-ciphertext",
        "private_code_digest": b"synthetic-digest-appointment-001",
        "first_name": "Clienta",
        "last_name": "De Prueba",
        "phone": "5510000000",
        "email": "clienta@example.test",
        "service_id": service_id,
        "service_snapshot_name": "Servicio para cita",
        "service_snapshot_duration_minutes": 60,
        "service_snapshot_price": Decimal("350.00"),
        "branch": "chiconcuac",
        "scheduled_start": datetime(2030, 6, 15, 17, tzinfo=timezone.utc),
        "scheduled_end": datetime(2030, 6, 15, 18, tzinfo=timezone.utc),
        "status": "scheduled",
        "cancellation_reason": None,
        "origin": "public",
        "created_by_account_id": None,
        "privacy_notice_version_id": privacy_notice_version_id,
        "privacy_notice_accepted_at": datetime(2030, 6, 1, tzinfo=timezone.utc),
        "contact_processing_authorized": True,
        "adult_responsibility_declared": True,
        **overrides,
    }


def insert_appointment(connection: Connection, values: dict[str, object]) -> None:
    connection.execute(
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
                :private_code_ciphertext, :private_code_digest, :first_name,
                :last_name, :phone, :email, :service_id, :service_snapshot_name,
                :service_snapshot_duration_minutes, :service_snapshot_price, :branch,
                :scheduled_start, :scheduled_end, :status, :cancellation_reason,
                :origin, :created_by_account_id, :privacy_notice_version_id,
                :privacy_notice_accepted_at, :contact_processing_authorized,
                :adult_responsibility_declared
            )
            """
        ),
        values,
    )


def valid_confirmation_reference_parameters(
    appointment_id: int | None = None, **overrides: object
) -> dict[str, object]:
    generated_at = datetime(2030, 6, 1, 12, tzinfo=timezone.utc)
    return {
        "reference_digest": b"synthetic-confirmation-reference-digest-001",
        "generated_at": generated_at,
        "expires_at": generated_at.replace(day=2),
        "consumed_at": None,
        "appointment_id": appointment_id,
        **overrides,
    }


def insert_confirmation_reference(
    connection: Connection, values: dict[str, object]
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO booking_confirmation_references (
                reference_digest, generated_at, expires_at, consumed_at, appointment_id
            ) VALUES (
                :reference_digest, :generated_at, :expires_at, :consumed_at,
                :appointment_id
            )
            """
        ),
        values,
    )


def valid_notification_delivery_parameters(
    appointment_id: int, **overrides: object
) -> dict[str, object]:
    return {
        "appointment_id": appointment_id,
        "event": "appointment_created",
        "channel": "email",
        "status": "pending",
        "status_changed_at": datetime(2030, 6, 1, 12, tzinfo=timezone.utc),
        "external_reference": None,
        "appointment_reminder_id": None,
        "previous_delivery_id": None,
        "sanitized_error": None,
        **overrides,
    }


def insert_notification_delivery(
    connection: Connection, values: dict[str, object]
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO notification_deliveries (
                appointment_id, event, channel, status, status_changed_at,
                external_reference, appointment_reminder_id, previous_delivery_id,
                sanitized_error
            ) VALUES (
                :appointment_id, :event, :channel, :status, :status_changed_at,
                :external_reference, :appointment_reminder_id,
                :previous_delivery_id, :sanitized_error
            )
            """
        ),
        values,
    )


def valid_appointment_reminder_parameters(
    appointment_id: int, **overrides: object
) -> dict[str, object]:
    appointment_scheduled_start = datetime(2030, 6, 15, 17, tzinfo=timezone.utc)
    return {
        "appointment_id": appointment_id,
        "appointment_scheduled_start": appointment_scheduled_start,
        "send_at": appointment_scheduled_start - timedelta(hours=24),
        "status": "scheduled",
        "status_changed_at": datetime(2030, 6, 1, 12, tzinfo=timezone.utc),
        "claimed_at": None,
        "claim_expires_at": None,
        **overrides,
    }


def insert_appointment_reminder(
    connection: Connection, values: dict[str, object]
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO appointment_reminders (
                appointment_id, appointment_scheduled_start, send_at, status,
                status_changed_at, claimed_at, claim_expires_at
            ) VALUES (
                :appointment_id, :appointment_scheduled_start, :send_at, :status,
                :status_changed_at, :claimed_at, :claim_expires_at
            )
            """
        ),
        values,
    )


def valid_availability_block_parameters(**overrides: object) -> dict[str, object]:
    return {
        "scope": "global",
        "branch": None,
        "starts_at": datetime(2030, 6, 15, 17, tzinfo=timezone.utc),
        "ends_at": datetime(2030, 6, 15, 18, tzinfo=timezone.utc),
        "created_by_account_id": 1,
        **overrides,
    }


def insert_availability_block(
    connection: Connection, values: dict[str, object]
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO availability_blocks (
                scope, branch, starts_at, ends_at, created_by_account_id
            ) VALUES (
                :scope, :branch, :starts_at, :ends_at, :created_by_account_id
            )
            """
        ),
        values,
    )


def valid_public_request_event_parameters(**overrides: object) -> dict[str, object]:
    occurred_at = datetime(2030, 6, 1, 12, tzinfo=timezone.utc)
    return {
        "category": "appointment_lookup",
        "result": "failed",
        "subject_fingerprint": b"synthetic-keyed-fingerprint",
        "occurred_at": occurred_at,
        "expires_at": occurred_at + timedelta(minutes=15),
        **overrides,
    }


def insert_public_request_event(
    connection: Connection, values: dict[str, object]
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO public_request_events (
                category, result, subject_fingerprint, occurred_at, expires_at
            ) VALUES (
                :category, :result, :subject_fingerprint, :occurred_at, :expires_at
            )
            """
        ),
        values,
    )


@pytest.mark.integration
def test_initial_migration_creates_approved_tables_and_columns(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)

    assert {
        "services",
        "monthly_appointment_statistics",
        "public_request_events",
        "privacy_notice_versions",
        "appointments",
        "booking_confirmation_references",
        "notification_deliveries",
        "appointment_reminders",
        "availability_blocks",
        "schedule_guard",
        "alembic_version",
    }.issubset(
        set(inspector.get_table_names())
    )
    assert {
        "service_id",
        "name",
        "canonical_name",
        "description",
        "duration_minutes",
        "price",
        "is_active",
        "available_chiconcuac",
        "available_texcoco",
        "created_at",
        "updated_at",
    } == {column["name"] for column in inspector.get_columns("services")}
    assert {
        "monthly_appointment_statistic_id",
        "month_start",
        "service_id",
        "branch",
        "status",
        "appointment_count",
        "created_at",
        "updated_at",
    } == {
        column["name"]
        for column in inspector.get_columns("monthly_appointment_statistics")
    }
    assert {
        "public_request_event_id",
        "category",
        "result",
        "subject_fingerprint",
        "occurred_at",
        "expires_at",
        "created_at",
    } == {
        column["name"] for column in inspector.get_columns("public_request_events")
    }
    assert {
        "privacy_notice_version_id",
        "version",
        "content",
        "published_at",
        "valid_from",
        "valid_until",
        "created_at",
    } == {
        column["name"]
        for column in inspector.get_columns("privacy_notice_versions")
    }
    assert {
        "appointment_id",
        "private_code_ciphertext",
        "private_code_digest",
        "first_name",
        "last_name",
        "phone",
        "email",
        "service_id",
        "service_snapshot_name",
        "service_snapshot_duration_minutes",
        "service_snapshot_price",
        "branch",
        "scheduled_start",
        "scheduled_end",
        "status",
        "cancellation_reason",
        "origin",
        "created_by_account_id",
        "privacy_notice_version_id",
        "privacy_notice_accepted_at",
        "contact_processing_authorized",
        "adult_responsibility_declared",
        "created_at",
        "updated_at",
    } == {column["name"] for column in inspector.get_columns("appointments")}
    assert {
        "booking_confirmation_reference_id",
        "reference_digest",
        "generated_at",
        "expires_at",
        "consumed_at",
        "appointment_id",
        "created_at",
    } == {
        column["name"]
        for column in inspector.get_columns("booking_confirmation_references")
    }
    assert {
        "notification_delivery_id",
        "appointment_id",
        "event",
        "channel",
        "status",
        "status_changed_at",
        "external_reference",
        "appointment_reminder_id",
        "previous_delivery_id",
        "sanitized_error",
        "created_at",
        "updated_at",
    } == {
        column["name"] for column in inspector.get_columns("notification_deliveries")
    }
    assert {
        "appointment_reminder_id",
        "appointment_id",
        "appointment_scheduled_start",
        "send_at",
        "status",
        "status_changed_at",
        "claimed_at",
        "claim_expires_at",
        "created_at",
        "updated_at",
    } == {
        column["name"] for column in inspector.get_columns("appointment_reminders")
    }
    assert {
        "availability_block_id",
        "scope",
        "branch",
        "starts_at",
        "ends_at",
        "created_by_account_id",
        "created_at",
        "updated_at",
    } == {column["name"] for column in inspector.get_columns("availability_blocks")}
    assert {"guard_id"} == {
        column["name"] for column in inspector.get_columns("schedule_guard")
    }


@pytest.mark.integration
def test_service_constraints_reject_invalid_values_and_duplicate_names(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            insert_service(connection, valid_service_parameters(name="Manicure"))

            assert connection.execute(
                text("SELECT canonical_name FROM services WHERE name = 'Manicure'")
            ).scalar_one() == "manicure"

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    insert_service(
                        connection,
                        valid_service_parameters(name="manicure"),
                    )

            invalid_values = [
                valid_service_parameters(duration_minutes=4),
                valid_service_parameters(duration_minutes=7),
                valid_service_parameters(duration_minutes=601),
                valid_service_parameters(price=Decimal("0.00")),
                valid_service_parameters(price=Decimal("12.345")),
                valid_service_parameters(price=Decimal("20000.01")),
                valid_service_parameters(
                    available_chiconcuac=False,
                    available_texcoco=False,
                ),
                valid_service_parameters(name=" Servicio con espacios "),
                valid_service_parameters(name=""),
            ]
            for values in invalid_values:
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        insert_service(connection, values)

            with pytest.raises(DataError):
                with connection.begin_nested():
                    insert_service(
                        connection,
                        valid_service_parameters(description="x" * 251),
                    )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_internal_service_creation_persists_a_valid_service(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            result = CreateService(
                PostgresServiceCreationRepository(connection)
            ).execute(
                CreateServiceCommand(
                    name="  Servicio interno  ",
                    description="  Descripción interna.  ",
                    duration_minutes=60,
                    price=Decimal("350.00"),
                    is_active=True,
                    branches=["chiconcuac"],
                )
            )

            persisted = connection.execute(
                text(
                    """
                    SELECT name, description, duration_minutes, price, is_active,
                           available_chiconcuac, available_texcoco
                    FROM services
                    WHERE service_id = :service_id
                    """
                ),
                {"service_id": result.service_id},
            ).one()
            assert persisted == (
                "Servicio interno",
                "Descripción interna.",
                60,
                Decimal("350.00"),
                True,
                True,
                False,
            )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_internal_service_edit_preserves_appointment_snapshots(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            service_id, privacy_notice_version_id = create_appointment_dependencies(
                connection
            )
            insert_appointment(
                connection,
                valid_appointment_parameters(service_id, privacy_notice_version_id),
            )

            result = EditService(PostgresServiceEditingRepository(connection)).execute(
                EditServiceCommand(
                    service_id=service_id,
                    name="Servicio editado",
                    description="Descripción editada.",
                    duration_minutes=90,
                    price=Decimal("500.00"),
                    branches=["texcoco"],
                )
            )

            assert result.service.name == "Servicio editado"
            assert connection.execute(
                text(
                    """
                    SELECT service_snapshot_name, service_snapshot_duration_minutes,
                           service_snapshot_price, branch
                    FROM appointments
                    WHERE service_id = :service_id
                    """
                ),
                {"service_id": service_id},
            ).one() == ("Servicio para cita", 60, Decimal("350.00"), "chiconcuac")
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_internal_service_status_changes_preserve_appointment_snapshots(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            service_id, privacy_notice_version_id = create_appointment_dependencies(
                connection
            )
            insert_appointment(
                connection,
                valid_appointment_parameters(service_id, privacy_notice_version_id),
            )
            use_case = SetServiceStatus(PostgresServiceStatusRepository(connection))

            assert use_case.execute(
                SetServiceStatusCommand(service_id, False)
            ).is_active is False
            assert connection.execute(
                text("SELECT is_active FROM services WHERE service_id = :service_id"),
                {"service_id": service_id},
            ).scalar_one() is False

            assert use_case.execute(
                SetServiceStatusCommand(service_id, True)
            ).is_active is True
            assert connection.execute(
                text(
                    """
                    SELECT service_snapshot_name, service_snapshot_duration_minutes,
                           service_snapshot_price, branch
                    FROM appointments
                    WHERE service_id = :service_id
                    """
                ),
                {"service_id": service_id},
            ).one() == ("Servicio para cita", 60, Decimal("350.00"), "chiconcuac")
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_public_catalog_excludes_inactive_and_other_branch_services(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            insert_service(
                connection,
                valid_service_parameters(name="Activo Chiconcuac"),
            )
            insert_service(
                connection,
                valid_service_parameters(
                    name="Inactivo Chiconcuac",
                    is_active=False,
                ),
            )
            insert_service(
                connection,
                valid_service_parameters(
                    name="Activo Texcoco",
                    available_chiconcuac=False,
                    available_texcoco=True,
                ),
            )

            services = ListActiveServices(
                PostgresActiveServiceCatalog(connection)
            ).execute("chiconcuac")

            assert {service.name for service in services} == {"Activo Chiconcuac"}
            assert all(service.price == Decimal("350.00") for service in services)
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_monthly_appointment_statistics_are_disassociated_and_unique(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            service_id = connection.execute(
                text(
                    """
                    INSERT INTO services (
                        name, description, duration_minutes, price, is_active,
                        available_chiconcuac, available_texcoco
                    ) VALUES (
                        :name, :description, :duration_minutes, :price, :is_active,
                        :available_chiconcuac, :available_texcoco
                    ) RETURNING service_id
                    """
                ),
                valid_service_parameters(name="Servicio para estadística"),
            ).scalar_one()
            values = {
                "month_start": date(2030, 6, 1),
                "service_id": service_id,
                "branch": "chiconcuac",
                "status": "completed",
                "appointment_count": 1,
            }
            connection.execute(
                text(
                    """
                    INSERT INTO monthly_appointment_statistics (
                        month_start, service_id, branch, status, appointment_count
                    ) VALUES (
                        :month_start, :service_id, :branch, :status,
                        :appointment_count
                    )
                    """
                ),
                values,
            )

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            INSERT INTO monthly_appointment_statistics (
                                month_start, service_id, branch, status,
                                appointment_count
                            ) VALUES (
                                :month_start, :service_id, :branch, :status,
                                :appointment_count
                            )
                            """
                        ),
                        values,
                    )

            invalid_values = [
                {**values, "month_start": date(2030, 6, 2)},
                {**values, "branch": "other"},
                {**values, "status": "invalid"},
                {**values, "appointment_count": -1},
                {**values, "service_id": 999999},
            ]
            for invalid_value in invalid_values:
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                INSERT INTO monthly_appointment_statistics (
                                    month_start, service_id, branch, status,
                                    appointment_count
                                ) VALUES (
                                    :month_start, :service_id, :branch, :status,
                                    :appointment_count
                                )
                                """
                            ),
                            invalid_value,
                        )

            columns = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "monthly_appointment_statistics"
                )
            }
            assert {"appointment_id", "private_code", "phone", "email"}.isdisjoint(
                columns
            )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_public_request_events_store_only_minimum_protection_data(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            values = valid_public_request_event_parameters()
            insert_public_request_event(connection, values)
            assert connection.execute(
                text(
                    """
                    SELECT category, result, subject_fingerprint, occurred_at, expires_at
                    FROM public_request_events
                    """
                )
            ).one() == (
                values["category"],
                values["result"],
                values["subject_fingerprint"],
                values["occurred_at"],
                values["expires_at"],
            )

            invalid_values = [
                valid_public_request_event_parameters(category="   "),
                valid_public_request_event_parameters(result="   "),
                valid_public_request_event_parameters(subject_fingerprint=b""),
                valid_public_request_event_parameters(
                    expires_at=datetime(2030, 6, 1, 12, tzinfo=timezone.utc)
                ),
            ]
            for invalid_value in invalid_values:
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        insert_public_request_event(connection, invalid_value)

            columns = {
                column["name"]
                for column in inspect(connection).get_columns("public_request_events")
            }
            assert {"ip_address", "private_code", "phone", "credential"}.isdisjoint(
                columns
            )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_privacy_notice_version_and_content_are_immutable(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    """
                    INSERT INTO privacy_notice_versions (
                        version, content, published_at, valid_from
                    ) VALUES (:version, :content, :published_at, :valid_from)
                    """
                ),
                {
                    "version": "synthetic-test-v1",
                    "content": "Synthetic test notice content",
                    "published_at": datetime.now(timezone.utc),
                    "valid_from": datetime.now(timezone.utc),
                },
            )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            UPDATE privacy_notice_versions
                            SET content = :content
                            WHERE version = :version
                            """
                        ),
                        {
                            "version": "synthetic-test-v1",
                            "content": "Changed synthetic test content",
                        },
                    )

            connection.execute(
                text(
                    """
                    UPDATE privacy_notice_versions
                    SET valid_until = :valid_until
                    WHERE version = :version
                    """
                ),
                {
                    "version": "synthetic-test-v1",
                    "valid_until": datetime(2030, 7, 1, tzinfo=timezone.utc),
                },
            )

            service_id, accepted_notice_version_id = create_appointment_dependencies(
                connection
            )
            accepted_appointment = valid_appointment_parameters(
                service_id,
                accepted_notice_version_id,
                private_code_digest=b"synthetic-accepted-notice-digest",
            )
            insert_appointment(connection, accepted_appointment)

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            UPDATE privacy_notice_versions
                            SET valid_until = :valid_until
                            WHERE privacy_notice_version_id = :notice_id
                            """
                        ),
                        {
                            "notice_id": accepted_notice_version_id,
                            "valid_until": datetime(
                                2030, 7, 1, tzinfo=timezone.utc
                            ),
                        },
                    )

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            DELETE FROM privacy_notice_versions
                            WHERE privacy_notice_version_id = :notice_id
                            """
                        ),
                        {"notice_id": accepted_notice_version_id},
                    )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_appointment_persists_snapshot_consent_and_required_constraints(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            service_id, privacy_notice_version_id = create_appointment_dependencies(
                connection
            )
            values = valid_appointment_parameters(
                service_id, privacy_notice_version_id
            )
            insert_appointment(connection, values)

            connection.execute(
                text(
                    """
                    UPDATE services
                    SET name = :name, duration_minutes = :duration_minutes,
                        price = :price
                    WHERE service_id = :service_id
                    """
                ),
                {
                    "name": "Servicio cambiado",
                    "duration_minutes": 90,
                    "price": Decimal("500.00"),
                    "service_id": service_id,
                },
            )
            snapshot = connection.execute(
                text(
                    """
                    SELECT service_snapshot_name, service_snapshot_duration_minutes,
                           service_snapshot_price, privacy_notice_version_id
                    FROM appointments
                    """
                )
            ).one()
            assert snapshot == (
                "Servicio para cita",
                60,
                Decimal("350.00"),
                privacy_notice_version_id,
            )

            public_consent = connection.execute(
                text(
                    """
                    SELECT privacy_notice_version_id, privacy_notice_accepted_at,
                           origin, contact_processing_authorized,
                           adult_responsibility_declared, created_by_account_id
                    FROM appointments
                    WHERE private_code_digest = :digest
                    """
                ),
                {"digest": values["private_code_digest"]},
            ).one()
            assert public_consent.privacy_notice_version_id == privacy_notice_version_id
            assert public_consent.privacy_notice_accepted_at == values[
                "privacy_notice_accepted_at"
            ]
            assert public_consent.origin == "public"
            assert public_consent.contact_processing_authorized is True
            assert public_consent.adult_responsibility_declared is True
            assert public_consent.created_by_account_id is None

            administrative_values = valid_appointment_parameters(
                service_id,
                privacy_notice_version_id,
                private_code_digest=b"synthetic-administrative-consent-digest",
                origin="administrative",
                created_by_account_id=23,
            )
            insert_appointment(connection, administrative_values)
            administrative_consent = connection.execute(
                text(
                    """
                    SELECT origin, created_by_account_id
                    FROM appointments
                    WHERE private_code_digest = :digest
                    """
                ),
                {"digest": administrative_values["private_code_digest"]},
            ).one()
            assert administrative_consent == ("administrative", 23)

            invalid_values = [
                valid_appointment_parameters(
                    service_id, privacy_notice_version_id, branch="other"
                ),
                valid_appointment_parameters(
                    service_id,
                    privacy_notice_version_id,
                    scheduled_end=datetime(2030, 6, 15, 17, tzinfo=timezone.utc),
                ),
                valid_appointment_parameters(
                    service_id, privacy_notice_version_id, status="invalid"
                ),
                valid_appointment_parameters(
                    service_id,
                    privacy_notice_version_id,
                    origin="administrative",
                ),
                valid_appointment_parameters(
                    service_id,
                    privacy_notice_version_id,
                    contact_processing_authorized=False,
                ),
                valid_appointment_parameters(
                    service_id, privacy_notice_version_id, phone="551000000"
                ),
                valid_appointment_parameters(
                    999999, privacy_notice_version_id,
                    private_code_digest=b"synthetic-digest-missing-service",
                ),
            ]
            for index, invalid_value in enumerate(invalid_values, start=1):
                invalid_value["private_code_digest"] = (
                    f"synthetic-invalid-digest-{index}".encode()
                )
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        insert_appointment(connection, invalid_value)

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    insert_appointment(connection, values)

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "DELETE FROM privacy_notice_versions "
                            "WHERE privacy_notice_version_id = :notice_id"
                        ),
                        {"notice_id": privacy_notice_version_id},
                    )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_confirmation_reference_enforces_digest_expiry_consumption_and_appointment_link(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            service_id, privacy_notice_version_id = create_appointment_dependencies(
                connection
            )
            appointment_values = valid_appointment_parameters(
                service_id, privacy_notice_version_id
            )
            insert_appointment(connection, appointment_values)
            appointment_id = connection.execute(
                text(
                    "SELECT appointment_id FROM appointments "
                    "WHERE private_code_digest = :digest"
                ),
                {"digest": appointment_values["private_code_digest"]},
            ).scalar_one()

            values = valid_confirmation_reference_parameters(appointment_id)
            insert_confirmation_reference(connection, values)

            persisted = connection.execute(
                text(
                    """
                    SELECT reference_digest, generated_at, expires_at, consumed_at,
                           appointment_id
                    FROM booking_confirmation_references
                    """
                )
            ).one()
            assert persisted == (
                values["reference_digest"],
                values["generated_at"],
                values["expires_at"],
                None,
                appointment_id,
            )

            invalid_values = [
                valid_confirmation_reference_parameters(
                    reference_digest=b"",
                ),
                valid_confirmation_reference_parameters(
                    reference_digest=b"synthetic-invalid-expiry",
                    expires_at=datetime(2030, 6, 2, 12, 1, tzinfo=timezone.utc),
                ),
                valid_confirmation_reference_parameters(
                    reference_digest=b"synthetic-invalid-consumption",
                    consumed_at=datetime(2030, 6, 2, 12, tzinfo=timezone.utc),
                ),
                valid_confirmation_reference_parameters(
                    reference_digest=b"synthetic-invalid-appointment",
                    appointment_id=999999,
                ),
            ]
            for invalid_value in invalid_values:
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        insert_confirmation_reference(connection, invalid_value)

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    insert_confirmation_reference(connection, values)

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    insert_confirmation_reference(
                        connection,
                        valid_confirmation_reference_parameters(
                            appointment_id,
                            reference_digest=b"synthetic-second-reference",
                        ),
                    )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_notification_deliveries_keep_channels_and_diagnostics_separate(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            service_id, privacy_notice_version_id = create_appointment_dependencies(
                connection
            )
            appointment_values = valid_appointment_parameters(
                service_id, privacy_notice_version_id
            )
            insert_appointment(connection, appointment_values)
            appointment_id = connection.execute(
                text(
                    "SELECT appointment_id FROM appointments "
                    "WHERE private_code_digest = :digest"
                ),
                {"digest": appointment_values["private_code_digest"]},
            ).scalar_one()

            email_delivery = valid_notification_delivery_parameters(appointment_id)
            insert_notification_delivery(connection, email_delivery)
            email_delivery_id = connection.execute(
                text(
                    "SELECT notification_delivery_id FROM notification_deliveries "
                    "WHERE channel = 'email'"
                )
            ).scalar_one()
            whatsapp_delivery = valid_notification_delivery_parameters(
                appointment_id,
                channel="whatsapp",
                status="failed",
                external_reference="provider-message-001",
                previous_delivery_id=email_delivery_id,
                sanitized_error="Provider rejected the request",
            )
            insert_notification_delivery(connection, whatsapp_delivery)

            persisted = connection.execute(
                text(
                    """
                    SELECT event, channel, status, external_reference,
                           previous_delivery_id, sanitized_error
                    FROM notification_deliveries
                    WHERE channel = 'whatsapp'
                    """
                )
            ).one()
            assert persisted == (
                "appointment_created",
                "whatsapp",
                "failed",
                "provider-message-001",
                email_delivery_id,
                "Provider rejected the request",
            )

            invalid_values = [
                valid_notification_delivery_parameters(appointment_id, event="   "),
                valid_notification_delivery_parameters(appointment_id, channel="sms"),
                valid_notification_delivery_parameters(appointment_id, status="sent"),
                valid_notification_delivery_parameters(
                    appointment_id, sanitized_error="   "
                ),
                valid_notification_delivery_parameters(999999),
                valid_notification_delivery_parameters(
                    appointment_id, previous_delivery_id=999999
                ),
            ]
            for invalid_value in invalid_values:
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        insert_notification_delivery(connection, invalid_value)

            delivery_columns = {
                column["name"]
                for column in inspect(connection).get_columns("notification_deliveries")
            }
            assert {"private_code", "phone", "email"}.isdisjoint(delivery_columns)
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_appointment_reminders_are_durable_unique_and_preserve_deliveries(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            service_id, privacy_notice_version_id = create_appointment_dependencies(
                connection
            )
            appointment_values = valid_appointment_parameters(
                service_id, privacy_notice_version_id
            )
            insert_appointment(connection, appointment_values)
            appointment_id = connection.execute(
                text(
                    "SELECT appointment_id FROM appointments "
                    "WHERE private_code_digest = :digest"
                ),
                {"digest": appointment_values["private_code_digest"]},
            ).scalar_one()

            reminder_values = valid_appointment_reminder_parameters(appointment_id)
            insert_appointment_reminder(connection, reminder_values)
            reminder_id = connection.execute(
                text(
                    "SELECT appointment_reminder_id FROM appointment_reminders "
                    "WHERE appointment_id = :appointment_id"
                ),
                {"appointment_id": appointment_id},
            ).scalar_one()
            insert_notification_delivery(
                connection,
                valid_notification_delivery_parameters(
                    appointment_id,
                    event="appointment_reminder",
                    appointment_reminder_id=reminder_id,
                ),
            )
            insert_notification_delivery(
                connection,
                valid_notification_delivery_parameters(
                    appointment_id,
                    event="appointment_reminder",
                    channel="whatsapp",
                    appointment_reminder_id=reminder_id,
                ),
            )

            persisted = connection.execute(
                text(
                    """
                    SELECT appointment_scheduled_start, send_at, status,
                           claimed_at, claim_expires_at
                    FROM appointment_reminders
                    WHERE appointment_reminder_id = :reminder_id
                    """
                ),
                {"reminder_id": reminder_id},
            ).one()
            assert persisted == (
                reminder_values["appointment_scheduled_start"],
                reminder_values["send_at"],
                "scheduled",
                None,
                None,
            )

            invalid_values = [
                valid_appointment_reminder_parameters(appointment_id),
                valid_appointment_reminder_parameters(
                    appointment_id,
                    send_at=reminder_values["send_at"] + timedelta(minutes=1),
                ),
                valid_appointment_reminder_parameters(appointment_id, status="due"),
                valid_appointment_reminder_parameters(appointment_id, status="claimed"),
                valid_appointment_reminder_parameters(
                    appointment_id,
                    claimed_at=datetime(2030, 6, 14, 17, tzinfo=timezone.utc),
                    claim_expires_at=datetime(2030, 6, 14, 16, 59, tzinfo=timezone.utc),
                ),
                valid_appointment_reminder_parameters(999999),
            ]
            for invalid_value in invalid_values:
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        insert_appointment_reminder(connection, invalid_value)

            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    insert_notification_delivery(
                        connection,
                        valid_notification_delivery_parameters(
                            appointment_id,
                            event="appointment_reminder",
                            appointment_reminder_id=reminder_id,
                        ),
                    )

            connection.execute(
                text(
                    """
                    UPDATE appointment_reminders
                    SET status = 'invalidated', status_changed_at = :changed_at
                    WHERE appointment_reminder_id = :reminder_id
                    """
                ),
                {
                    "changed_at": datetime(2030, 6, 2, 12, tzinfo=timezone.utc),
                    "reminder_id": reminder_id,
                },
            )
            assert connection.execute(
                text(
                    "SELECT count(*) FROM notification_deliveries "
                    "WHERE appointment_reminder_id = :reminder_id"
                ),
                {"reminder_id": reminder_id},
            ).scalar_one() == 2
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_availability_blocks_and_schedule_guard_enforce_persistent_shape(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            insert_availability_block(connection, valid_availability_block_parameters())
            insert_availability_block(
                connection,
                valid_availability_block_parameters(
                    scope="branch",
                    branch="chiconcuac",
                ),
            )
            assert connection.execute(
                text("SELECT count(*) FROM availability_blocks")
            ).scalar_one() == 2

            invalid_values = [
                valid_availability_block_parameters(scope="all"),
                valid_availability_block_parameters(branch="texcoco"),
                valid_availability_block_parameters(scope="branch", branch=None),
                valid_availability_block_parameters(scope="branch", branch="other"),
                valid_availability_block_parameters(
                    ends_at=datetime(2030, 6, 15, 17, tzinfo=timezone.utc)
                ),
            ]
            for invalid_value in invalid_values:
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        insert_availability_block(connection, invalid_value)

            assert connection.execute(
                text("SELECT guard_id FROM schedule_guard FOR UPDATE")
            ).scalar_one() == 1
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("INSERT INTO schedule_guard (guard_id) VALUES (2)")
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("INSERT INTO schedule_guard (guard_id) VALUES (1)")
                    )
        finally:
            transaction.rollback()
