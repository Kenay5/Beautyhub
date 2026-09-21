"""T080 PostgreSQL evidence for atomic public cancellation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, select

from backend.app.application.cancel_public_appointment import (
    CancelPublicAppointment,
    PublicAppointmentCancellationCommand,
    PublicAppointmentCancellationRepository,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    NotificationDelivery,
    PrivacyNoticeVersion,
    Service,
)
from backend.app.infrastructure.persistence.public_appointment_cancellation_repository import (
    PostgresPublicAppointmentCancellationRepository,
    PostgresPublicAppointmentCancellationUnitOfWork,
)
from backend.app.infrastructure.persistence.schedule_repository import (
    PostgresScheduleRepository,
)
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


@pytest.mark.integration
def test_t080_cancels_without_deleting_and_releases_the_schedule(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_cancellation_fixture(migrated_engine)
    try:
        result = _canceller(migrated_engine, fixture["now"]).execute(
            _command(fixture, reason="  Cambio de planes ✨  ")
        )

        with migrated_engine.connect() as connection:
            stored = connection.execute(
                select(
                    Appointment.appointment_id,
                    Appointment.private_code_digest,
                    Appointment.service_snapshot_name,
                    Appointment.branch,
                    Appointment.scheduled_start,
                    Appointment.scheduled_end,
                    Appointment.status,
                    Appointment.cancellation_reason,
                ).where(Appointment.appointment_id == fixture["appointment_id"])
            ).one()
            occupying_starts = {
                interval.interval.start
                for interval in PostgresScheduleRepository(connection).list_scheduled_intervals()
            }
            deliveries = connection.execute(
                select(
                    NotificationDelivery.event,
                    NotificationDelivery.channel,
                    NotificationDelivery.status,
                )
                .where(
                    NotificationDelivery.appointment_id
                    == fixture["appointment_id"]
                )
                .order_by(NotificationDelivery.channel)
            ).all()
            reminders = connection.execute(
                select(
                    AppointmentReminder.appointment_scheduled_start,
                    AppointmentReminder.status,
                ).where(
                    AppointmentReminder.appointment_id == fixture["appointment_id"]
                )
            ).all()

        assert result.status == "cancelled"
        assert stored.appointment_id == fixture["appointment_id"]
        assert stored.private_code_digest == fixture["private_code_digest"]
        assert stored.service_snapshot_name == fixture["service_name"]
        assert stored.branch == "chiconcuac"
        assert stored.scheduled_start == fixture["scheduled_start"]
        assert stored.scheduled_end == fixture["scheduled_start"] + timedelta(hours=1)
        assert stored.status == "cancelled"
        assert stored.cancellation_reason == "Cambio de planes ✨"
        assert fixture["scheduled_start"] not in occupying_starts
        assert [(row.event, row.channel, row.status) for row in deliveries] == [
            ("appointment_cancelled", "email", "pending"),
            ("appointment_cancelled", "whatsapp", "pending"),
        ]
        assert reminders == [(fixture["scheduled_start"], "invalidated")]
    finally:
        _cleanup_cancellation_fixture(migrated_engine, fixture)


class SyntheticPostCancellationFailure(RuntimeError):
    """Controlled failure raised after PostgreSQL receives the cancellation."""


class FailingAfterCancellationRepository(PostgresPublicAppointmentCancellationRepository):
    def cancel_appointment(self, **values: object) -> bool:
        super().cancel_appointment(**values)  # type: ignore[arg-type]
        raise SyntheticPostCancellationFailure("synthetic post-cancellation failure")


class FailingAfterCancellationUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentCancellationRepository]:
        with self._engine.begin() as connection:
            yield FailingAfterCancellationRepository(connection)


class SyntheticPostReminderCancellationFailure(RuntimeError):
    """Controlled failure after cancellation reminder invalidation."""


class FailingAfterReminderCancellationRepository(
    PostgresPublicAppointmentCancellationRepository
):
    def create_pending_deliveries(
        self,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> tuple[object, object]:
        raise SyntheticPostReminderCancellationFailure(
            "synthetic post-reminder cancellation failure"
        )


class FailingAfterReminderCancellationUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentCancellationRepository]:
        with self._engine.begin() as connection:
            yield FailingAfterReminderCancellationRepository(connection)


@pytest.mark.integration
def test_t080_rolls_back_status_and_reason_after_a_transaction_failure(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_cancellation_fixture(migrated_engine)
    service = CancelPublicAppointment(
        unit_of_work=FailingAfterCancellationUnitOfWork(migrated_engine),
        clock=FixedClock(fixture["now"]),  # type: ignore[arg-type]
    )
    try:
        with pytest.raises(SyntheticPostCancellationFailure):
            service.execute(_command(fixture, reason="Cambio controlado"))

        with migrated_engine.connect() as connection:
            stored = connection.execute(
                select(
                    Appointment.status,
                    Appointment.cancellation_reason,
                ).where(Appointment.appointment_id == fixture["appointment_id"])
            ).one()
            occupying_starts = {
                interval.interval.start
                for interval in PostgresScheduleRepository(connection).list_scheduled_intervals()
            }

        assert stored.status == "scheduled"
        assert stored.cancellation_reason is None
        assert fixture["scheduled_start"] in occupying_starts
    finally:
        _cleanup_cancellation_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t093c_rolls_back_cancellation_and_reminder_after_a_later_failure(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_cancellation_fixture(migrated_engine)
    service = CancelPublicAppointment(
        unit_of_work=FailingAfterReminderCancellationUnitOfWork(migrated_engine),
        clock=FixedClock(fixture["now"]),  # type: ignore[arg-type]
    )
    try:
        with pytest.raises(SyntheticPostReminderCancellationFailure):
            service.execute(_command(fixture, reason="Cambio controlado"))

        with migrated_engine.connect() as connection:
            appointment = connection.execute(
                select(
                    Appointment.status,
                    Appointment.cancellation_reason,
                ).where(Appointment.appointment_id == fixture["appointment_id"])
            ).one()
            reminder = connection.execute(
                select(AppointmentReminder.status).where(
                    AppointmentReminder.appointment_id == fixture["appointment_id"]
                )
            ).scalar_one()

        assert appointment.status == "scheduled"
        assert appointment.cancellation_reason is None
        assert reminder == "scheduled"
    finally:
        _cleanup_cancellation_fixture(migrated_engine, fixture)


def _canceller(engine: Engine, current_time: object) -> CancelPublicAppointment:
    return CancelPublicAppointment(
        unit_of_work=PostgresPublicAppointmentCancellationUnitOfWork(engine),
        clock=FixedClock(current_time),  # type: ignore[arg-type]
    )


def _command(
    fixture: dict[str, object],
    *,
    reason: str | None,
) -> PublicAppointmentCancellationCommand:
    return PublicAppointmentCancellationCommand(
        private_code_digest=fixture["private_code_digest"],  # type: ignore[arg-type]
        phone="55 1000 0000",
        reason=reason,
    )


def _seed_cancellation_fixture(engine: Engine) -> dict[str, object]:
    marker = uuid4().hex
    business_date = _unused_business_date(engine)
    now = datetime.combine(
        business_date,
        time(hour=9),
        tzinfo=BUSINESS_TIME_ZONE,
    )
    scheduled_start = now + timedelta(hours=1)
    private_code_digest = f"synthetic-cancellation-{marker}".encode("ascii")
    service_name = f"Servicio cancelación {marker}"

    with engine.begin() as connection:
        privacy_notice_version_id = connection.execute(
            PrivacyNoticeVersion.__table__.insert()
            .values(
                version=f"synthetic-cancellation-{marker}",
                content="Synthetic privacy notice for a cancellation test.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()
        service_id = connection.execute(
            Service.__table__.insert()
            .values(
                name=service_name,
                description="Synthetic cancellation service.",
                duration_minutes=60,
                price=350,
                is_active=True,
                available_chiconcuac=True,
                available_texcoco=True,
            )
            .returning(Service.service_id)
        ).scalar_one()
        appointment_id = connection.execute(
            Appointment.__table__.insert()
            .values(
                private_code_ciphertext=b"synthetic-ciphertext",
                private_code_digest=private_code_digest,
                first_name="Clienta",
                last_name="Sintética",
                phone="5510000000",
                email="clienta@example.test",
                service_id=service_id,
                service_snapshot_name=service_name,
                service_snapshot_duration_minutes=60,
                service_snapshot_price=350,
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
        connection.execute(
            AppointmentReminder.__table__.insert().values(
                appointment_id=appointment_id,
                appointment_scheduled_start=scheduled_start,
                send_at=scheduled_start - timedelta(hours=24),
                status="scheduled",
                status_changed_at=now - timedelta(days=2),
                claimed_at=None,
                claim_expires_at=None,
            )
        )

    return {
        "now": now,
        "scheduled_start": scheduled_start,
        "private_code_digest": private_code_digest,
        "appointment_id": appointment_id,
        "service_id": service_id,
        "service_name": service_name,
        "privacy_notice_version_id": privacy_notice_version_id,
    }


def _unused_business_date(engine: Engine) -> date:
    today = datetime.now(tz=BUSINESS_TIME_ZONE).date()
    for day_offset in range(60, 80):
        candidate = today + timedelta(days=day_offset)
        starts_at = datetime.combine(candidate, time.min, tzinfo=BUSINESS_TIME_ZONE)
        ends_at = starts_at + timedelta(days=1)
        with engine.connect() as connection:
            count = connection.execute(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.status == "scheduled",
                    Appointment.scheduled_start >= starts_at,
                    Appointment.scheduled_start < ends_at,
                )
            ).scalar_one()
        if count == 0:
            return candidate
    raise AssertionError("No unused synthetic business date was found.")


def _cleanup_cancellation_fixture(
    engine: Engine,
    fixture: dict[str, object],
) -> None:
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
