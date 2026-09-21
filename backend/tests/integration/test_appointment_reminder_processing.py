"""T093F PostgreSQL evidence for reminder start and appointment-change races."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, insert, select

from backend.app.application.cancel_public_appointment import (
    CancelPublicAppointment,
    PublicAppointmentCancellationCommand,
    PublicAppointmentCancellationRepository,
)
from backend.app.application.change_appointment_with_notifications import (
    CancelPublicAppointmentWithNotifications,
)
from backend.app.application.clock import FixedClock
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.process_claimed_appointment_reminder import (
    ClaimedAppointmentReminderRepository,
    ProcessClaimedAppointmentReminder,
    ProcessClaimedReminderCommand,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.appointment_reminder_processing_repository import (
    PostgresClaimedAppointmentReminderRepository,
    PostgresClaimedAppointmentReminderUnitOfWork,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    NotificationDelivery,
    PrivacyNoticeVersion,
    Service,
)
from backend.app.infrastructure.persistence.notification_delivery_result_writer import (
    PostgresNotificationDeliveryResultWriter,
)
from backend.app.infrastructure.persistence.public_appointment_cancellation_repository import (
    PostgresPublicAppointmentCancellationRepository,
)
from backend.app.infrastructure.settings import load_test_database_url
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator


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


@pytest.mark.integration
def test_t093f_channel_results_are_independent_and_never_change_the_appointment(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_claimed_reminder(migrated_engine)
    processor, email, whatsapp = _processor(
        migrated_engine,
        fixture,
        email_outcome="failed",
        whatsapp_outcome="accepted",
    )
    try:
        before = _appointment_state(migrated_engine, fixture)

        result = processor.execute(_process_command(fixture))

        assert result.outcome == "processed"
        assert tuple(delivery.status for delivery in result.deliveries) == (
            "failed",
            "accepted",
        )
        assert len(email.notifications) == len(whatsapp.notifications) == 1
        assert _appointment_state(migrated_engine, fixture) == before
        assert _reminder_state(migrated_engine, fixture) == (
            "completed",
            None,
            None,
        )
        assert _delivery_rows(migrated_engine, fixture) == [
            ("appointment_reminder", "email", "failed"),
            ("appointment_reminder", "whatsapp", "accepted"),
        ]
    finally:
        _cleanup(migrated_engine, fixture)


@pytest.mark.integration
def test_t093h_concurrent_processors_create_one_delivery_per_channel_only(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_claimed_reminder(migrated_engine)
    barrier = Barrier(2)

    def process():
        processor, email, whatsapp = _processor(migrated_engine, fixture)
        barrier.wait(timeout=10)
        result = processor.execute(_process_command(fixture))
        return result, email, whatsapp

    try:
        before = _appointment_state(migrated_engine, fixture)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                future.result(timeout=20)
                for future in (executor.submit(process), executor.submit(process))
            )

        assert sorted(result.outcome for result, _, _ in results) == [
            "processed",
            "skipped",
        ]
        assert sum(len(email.notifications) for _, email, _ in results) == 1
        assert sum(len(whatsapp.notifications) for _, _, whatsapp in results) == 1
        assert _delivery_rows(migrated_engine, fixture) == [
            ("appointment_reminder", "email", "accepted"),
            ("appointment_reminder", "whatsapp", "accepted"),
        ]
        assert _reminder_state(migrated_engine, fixture) == (
            "completed",
            None,
            None,
        )
        assert _appointment_state(migrated_engine, fixture) == before
    finally:
        _cleanup(migrated_engine, fixture)


@pytest.mark.integration
def test_t093f_change_committed_first_prevents_the_waiting_reminder(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_claimed_reminder(migrated_engine)
    appointment_changed = Event()
    allow_change_commit = Event()
    reminder_attempting_lock = Event()
    cancellation_uow = PausingCancellationUnitOfWork(
        migrated_engine,
        appointment_changed=appointment_changed,
        allow_commit=allow_change_commit,
    )
    processing_uow = SignalingProcessingUnitOfWork(
        migrated_engine,
        attempting_lock=reminder_attempting_lock,
    )
    cancellation, cancellation_email, cancellation_whatsapp = _canceller(
        migrated_engine,
        fixture,
        unit_of_work=cancellation_uow,
    )
    processor, reminder_email, reminder_whatsapp = _processor(
        migrated_engine,
        fixture,
        unit_of_work=processing_uow,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            cancellation_future = executor.submit(
                cancellation.execute,
                _cancel_command(fixture),
            )
            assert appointment_changed.wait(timeout=10)
            reminder_future = executor.submit(
                processor.execute,
                _process_command(fixture),
            )
            assert reminder_attempting_lock.wait(timeout=10)
            allow_change_commit.set()
            cancelled = cancellation_future.result(timeout=20)
            reminder_result = reminder_future.result(timeout=20)

        assert cancelled.status == "cancelled"
        assert reminder_result.outcome == "skipped"
        assert reminder_email.notifications == reminder_whatsapp.notifications == ()
        assert len(cancellation_email.notifications) == 1
        assert len(cancellation_whatsapp.notifications) == 1
        assert _reminder_state(migrated_engine, fixture) == (
            "invalidated",
            None,
            None,
        )
        assert _delivery_rows(migrated_engine, fixture) == [
            ("appointment_cancelled", "email", "accepted"),
            ("appointment_cancelled", "whatsapp", "accepted"),
        ]
    finally:
        allow_change_commit.set()
        _cleanup(migrated_engine, fixture)


@pytest.mark.integration
def test_t093f_registered_start_first_survives_the_later_change_and_both_notify(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_claimed_reminder(migrated_engine)
    reminder_started = Event()
    allow_start_commit = Event()
    cancellation_attempting_lock = Event()
    processing_uow = PausingProcessingUnitOfWork(
        migrated_engine,
        registered_start=reminder_started,
        allow_commit=allow_start_commit,
    )
    cancellation_uow = SignalingCancellationUnitOfWork(
        migrated_engine,
        attempting_lock=cancellation_attempting_lock,
    )
    processor, reminder_email, reminder_whatsapp = _processor(
        migrated_engine,
        fixture,
        unit_of_work=processing_uow,
    )
    cancellation, cancellation_email, cancellation_whatsapp = _canceller(
        migrated_engine,
        fixture,
        unit_of_work=cancellation_uow,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            reminder_future = executor.submit(
                processor.execute,
                _process_command(fixture),
            )
            assert reminder_started.wait(timeout=10)
            cancellation_future = executor.submit(
                cancellation.execute,
                _cancel_command(fixture),
            )
            assert cancellation_attempting_lock.wait(timeout=10)
            allow_start_commit.set()
            reminder_result = reminder_future.result(timeout=20)
            cancelled = cancellation_future.result(timeout=20)

        assert reminder_result.outcome == "processed"
        assert cancelled.status == "cancelled"
        assert len(reminder_email.notifications) == 1
        assert len(reminder_whatsapp.notifications) == 1
        assert len(cancellation_email.notifications) == 1
        assert len(cancellation_whatsapp.notifications) == 1
        assert _reminder_state(migrated_engine, fixture) == (
            "completed",
            None,
            None,
        )
        assert _delivery_rows(migrated_engine, fixture) == [
            ("appointment_cancelled", "email", "accepted"),
            ("appointment_cancelled", "whatsapp", "accepted"),
            ("appointment_reminder", "email", "accepted"),
            ("appointment_reminder", "whatsapp", "accepted"),
        ]
        assert _appointment_state(migrated_engine, fixture)[-2:] == (
            "cancelled",
            "Cambio sintético",
        )
    finally:
        allow_start_commit.set()
        _cleanup(migrated_engine, fixture)


class PausingCancellationRepository(PostgresPublicAppointmentCancellationRepository):
    def __init__(
        self,
        connection,
        *,
        appointment_changed: Event,
        allow_commit: Event,
    ) -> None:
        super().__init__(connection)
        self._appointment_changed = appointment_changed
        self._allow_commit = allow_commit

    def cancel_appointment(self, **values: object) -> bool:
        changed = super().cancel_appointment(**values)  # type: ignore[arg-type]
        self._appointment_changed.set()
        if not self._allow_commit.wait(timeout=10):
            raise TimeoutError("synthetic cancellation release timed out.")
        return changed


class PausingCancellationUnitOfWork:
    def __init__(
        self,
        engine: Engine,
        *,
        appointment_changed: Event,
        allow_commit: Event,
    ) -> None:
        self._engine = engine
        self._appointment_changed = appointment_changed
        self._allow_commit = allow_commit

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentCancellationRepository]:
        with self._engine.begin() as connection:
            yield PausingCancellationRepository(
                connection,
                appointment_changed=self._appointment_changed,
                allow_commit=self._allow_commit,
            )


class SignalingCancellationRepository(PostgresPublicAppointmentCancellationRepository):
    def __init__(self, connection, *, attempting_lock: Event) -> None:
        super().__init__(connection)
        self._attempting_lock = attempting_lock

    def lock_appointment_by_private_code_digest(self, private_code_digest: bytes):
        self._attempting_lock.set()
        return super().lock_appointment_by_private_code_digest(private_code_digest)


class SignalingCancellationUnitOfWork:
    def __init__(self, engine: Engine, *, attempting_lock: Event) -> None:
        self._engine = engine
        self._attempting_lock = attempting_lock

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentCancellationRepository]:
        with self._engine.begin() as connection:
            yield SignalingCancellationRepository(
                connection,
                attempting_lock=self._attempting_lock,
            )


class SignalingProcessingRepository(PostgresClaimedAppointmentReminderRepository):
    def __init__(self, connection, *, attempting_lock: Event) -> None:
        super().__init__(connection)
        self._attempting_lock = attempting_lock

    def lock_reminder_and_appointment(self, *, reminder_id: int):
        self._attempting_lock.set()
        return super().lock_reminder_and_appointment(reminder_id=reminder_id)


class SignalingProcessingUnitOfWork:
    def __init__(self, engine: Engine, *, attempting_lock: Event) -> None:
        self._engine = engine
        self._attempting_lock = attempting_lock

    @contextmanager
    def transaction(self) -> Iterator[ClaimedAppointmentReminderRepository]:
        with self._engine.begin() as connection:
            yield SignalingProcessingRepository(
                connection,
                attempting_lock=self._attempting_lock,
            )


class PausingProcessingRepository(PostgresClaimedAppointmentReminderRepository):
    def __init__(
        self,
        connection,
        *,
        registered_start: Event,
        allow_commit: Event,
    ) -> None:
        super().__init__(connection)
        self._registered_start = registered_start
        self._allow_commit = allow_commit

    def create_delivery_intents(self, **values: object):
        deliveries = super().create_delivery_intents(**values)  # type: ignore[arg-type]
        self._registered_start.set()
        if not self._allow_commit.wait(timeout=10):
            raise TimeoutError("synthetic reminder release timed out.")
        return deliveries


class PausingProcessingUnitOfWork:
    def __init__(
        self,
        engine: Engine,
        *,
        registered_start: Event,
        allow_commit: Event,
    ) -> None:
        self._engine = engine
        self._registered_start = registered_start
        self._allow_commit = allow_commit

    @contextmanager
    def transaction(self) -> Iterator[ClaimedAppointmentReminderRepository]:
        with self._engine.begin() as connection:
            yield PausingProcessingRepository(
                connection,
                registered_start=self._registered_start,
                allow_commit=self._allow_commit,
            )


def _processor(
    engine: Engine,
    fixture: dict[str, object],
    *,
    email_outcome: str = "accepted",
    whatsapp_outcome: str = "accepted",
    unit_of_work=None,
):
    email = EmailSimulator(outcome=email_outcome)  # type: ignore[arg-type]
    whatsapp = WhatsAppSimulator(outcome=whatsapp_outcome)  # type: ignore[arg-type]
    service = ProcessClaimedAppointmentReminder(
        unit_of_work=(
            unit_of_work or PostgresClaimedAppointmentReminderUnitOfWork(engine)
        ),
        dispatcher=NotificationDispatcher(
            email_port=email,
            whatsapp_port=whatsapp,
            result_writer=PostgresNotificationDeliveryResultWriter(engine),
        ),
        clock=FixedClock(fixture["now"]),  # type: ignore[arg-type]
    )
    return service, email, whatsapp


def _canceller(
    engine: Engine,
    fixture: dict[str, object],
    *,
    unit_of_work,
):
    email = EmailSimulator(outcome="accepted")
    whatsapp = WhatsAppSimulator(outcome="accepted")
    service = CancelPublicAppointmentWithNotifications(
        canceller=CancelPublicAppointment(
            unit_of_work=unit_of_work,
            clock=FixedClock(fixture["now"]),  # type: ignore[arg-type]
        ),
        dispatcher=NotificationDispatcher(
            email_port=email,
            whatsapp_port=whatsapp,
            result_writer=PostgresNotificationDeliveryResultWriter(engine),
        ),
        clock=FixedClock(fixture["now"]),  # type: ignore[arg-type]
    )
    return service, email, whatsapp


def _process_command(fixture: dict[str, object]) -> ProcessClaimedReminderCommand:
    return ProcessClaimedReminderCommand(
        reminder_id=fixture["reminder_id"],  # type: ignore[arg-type]
        claimed_at=fixture["claimed_at"],  # type: ignore[arg-type]
    )


def _cancel_command(fixture: dict[str, object]) -> PublicAppointmentCancellationCommand:
    return PublicAppointmentCancellationCommand(
        private_code_digest=fixture["private_code_digest"],  # type: ignore[arg-type]
        phone="5510000000",
        reason="Cambio sintético",
    )


def _seed_claimed_reminder(engine: Engine) -> dict[str, object]:
    marker = uuid4().hex
    now = datetime.now(tz=BUSINESS_TIME_ZONE).replace(microsecond=0)
    claimed_at = now - timedelta(minutes=1)
    scheduled_start = now + timedelta(hours=2)
    private_code_digest = f"synthetic-reminder-processing-{marker}".encode("ascii")
    with engine.begin() as connection:
        privacy_notice_version_id = connection.execute(
            insert(PrivacyNoticeVersion)
            .values(
                version=f"synthetic-reminder-processing-{marker}",
                content="Synthetic privacy notice for reminder processing.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()
        service_id = connection.execute(
            insert(Service)
            .values(
                name=f"Servicio recordatorio procesado {marker}",
                description="Synthetic reminder processing service.",
                duration_minutes=60,
                price=Decimal("350.00"),
                is_active=True,
                available_chiconcuac=True,
                available_texcoco=True,
            )
            .returning(Service.service_id)
        ).scalar_one()
        appointment_id = connection.execute(
            insert(Appointment)
            .values(
                private_code_ciphertext=b"synthetic-ciphertext",
                private_code_digest=private_code_digest,
                first_name="Clienta",
                last_name="Sintética",
                phone="5510000000",
                email="clienta@example.test",
                service_id=service_id,
                service_snapshot_name=f"Servicio recordatorio procesado {marker}",
                service_snapshot_duration_minutes=60,
                service_snapshot_price=Decimal("350.00"),
                branch="chiconcuac",
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_start + timedelta(hours=1),
                status="scheduled",
                cancellation_reason=None,
                origin="public",
                created_by_account_id=None,
                privacy_notice_version_id=privacy_notice_version_id,
                privacy_notice_accepted_at=now,
                contact_processing_authorized=True,
                adult_responsibility_declared=True,
            )
            .returning(Appointment.appointment_id)
        ).scalar_one()
        reminder_id = connection.execute(
            insert(AppointmentReminder)
            .values(
                appointment_id=appointment_id,
                appointment_scheduled_start=scheduled_start,
                send_at=scheduled_start - timedelta(hours=24),
                status="claimed",
                status_changed_at=claimed_at,
                claimed_at=claimed_at,
                claim_expires_at=now + timedelta(minutes=4),
            )
            .returning(AppointmentReminder.appointment_reminder_id)
        ).scalar_one()
    return {
        "now": now,
        "claimed_at": claimed_at,
        "appointment_id": appointment_id,
        "reminder_id": reminder_id,
        "private_code_digest": private_code_digest,
        "service_id": service_id,
        "privacy_notice_version_id": privacy_notice_version_id,
    }


def _appointment_state(engine: Engine, fixture: dict[str, object]):
    with engine.connect() as connection:
        return connection.execute(
            select(
                Appointment.scheduled_start,
                Appointment.scheduled_end,
                Appointment.branch,
                Appointment.service_snapshot_name,
                Appointment.service_snapshot_duration_minutes,
                Appointment.service_snapshot_price,
                Appointment.phone,
                Appointment.email,
                Appointment.status,
                Appointment.cancellation_reason,
            ).where(Appointment.appointment_id == fixture["appointment_id"])
        ).one()


def _reminder_state(engine: Engine, fixture: dict[str, object]):
    with engine.connect() as connection:
        return connection.execute(
            select(
                AppointmentReminder.status,
                AppointmentReminder.claimed_at,
                AppointmentReminder.claim_expires_at,
            ).where(
                AppointmentReminder.appointment_reminder_id
                == fixture["reminder_id"]
            )
        ).one()


def _delivery_rows(engine: Engine, fixture: dict[str, object]):
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                NotificationDelivery.event,
                NotificationDelivery.channel,
                NotificationDelivery.status,
            )
            .where(NotificationDelivery.appointment_id == fixture["appointment_id"])
            .order_by(NotificationDelivery.event, NotificationDelivery.channel)
        ).all()
    return [(row.event, row.channel, row.status) for row in rows]


def _cleanup(engine: Engine, fixture: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(Appointment).where(
                Appointment.appointment_id == fixture["appointment_id"]
            )
        )
        connection.execute(
            delete(Service).where(Service.service_id == fixture["service_id"])
        )
        connection.execute(
            delete(PrivacyNoticeVersion).where(
                PrivacyNoticeVersion.privacy_notice_version_id
                == fixture["privacy_notice_version_id"]
            )
        )
