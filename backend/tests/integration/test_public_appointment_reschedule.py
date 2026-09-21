"""T075/T076 PostgreSQL evidence for public appointment reprogramming."""

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

from backend.app.application.clock import FixedClock
from backend.app.application.reschedule_public_appointment import (
    PublicAppointmentRescheduleCommand,
    PublicAppointmentRescheduleConflictError,
    PublicAppointmentRescheduleRepository,
    ReschedulePublicAppointment,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    NotificationDelivery,
    PrivacyNoticeVersion,
    Service,
)
from backend.app.infrastructure.persistence.public_appointment_reschedule_repository import (
    PostgresPublicAppointmentRescheduleRepository,
    PostgresPublicAppointmentRescheduleUnitOfWork,
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
def test_t075_commits_a_revalidated_reschedule_and_excludes_its_current_row(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reschedule_fixture(migrated_engine)
    try:
        result = _rescheduler(migrated_engine, fixture["now"]).execute(
            _command(fixture, fixture["available_start"]),
        )

        with migrated_engine.connect() as connection:
            stored = connection.execute(
                select(
                    Appointment.service_id,
                    Appointment.service_snapshot_name,
                    Appointment.service_snapshot_duration_minutes,
                    Appointment.service_snapshot_price,
                    Appointment.private_code_digest,
                    Appointment.private_code_ciphertext,
                    Appointment.branch,
                    Appointment.scheduled_start,
                    Appointment.scheduled_end,
                    Appointment.status,
                ).where(Appointment.appointment_id == fixture["appointment_id"])
            ).one()
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

        assert result.appointment_id == fixture["appointment_id"]
        assert stored.service_id == fixture["target_service_id"]
        assert stored.service_snapshot_name == fixture["target_service_name"]
        assert stored.service_snapshot_duration_minutes == 90
        assert stored.service_snapshot_price == 450
        assert stored.private_code_digest == fixture["private_code_digest"]
        assert stored.private_code_ciphertext == fixture["private_code_ciphertext"]
        assert stored.branch == "texcoco"
        assert stored.scheduled_start == fixture["available_start"]
        assert stored.scheduled_end == fixture["available_start"] + timedelta(minutes=90)
        assert stored.status == "scheduled"
        assert [(row.event, row.channel, row.status) for row in deliveries] == [
            ("appointment_modified", "email", "pending"),
            ("appointment_modified", "whatsapp", "pending"),
        ]
    finally:
        _cleanup_reschedule_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t076_moving_date_or_branch_keeps_the_existing_service_snapshot(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reschedule_fixture(migrated_engine)
    try:
        _rescheduler(migrated_engine, fixture["now"]).execute(
            _command(
                fixture,
                fixture["available_start"],
                service_name=fixture["original_service_name"],
            ),
        )

        with migrated_engine.connect() as connection:
            stored = connection.execute(
                select(
                    Appointment.service_id,
                    Appointment.service_snapshot_name,
                    Appointment.service_snapshot_duration_minutes,
                    Appointment.service_snapshot_price,
                    Appointment.private_code_digest,
                    Appointment.private_code_ciphertext,
                    Appointment.branch,
                    Appointment.scheduled_start,
                    Appointment.scheduled_end,
                ).where(Appointment.appointment_id == fixture["appointment_id"])
            ).one()

        assert stored.service_id == fixture["original_service_id"]
        assert stored.service_snapshot_name == fixture["original_service_name"]
        assert stored.service_snapshot_duration_minutes == 60
        assert stored.service_snapshot_price == 350
        assert stored.private_code_digest == fixture["private_code_digest"]
        assert stored.private_code_ciphertext == fixture["private_code_ciphertext"]
        assert stored.branch == "texcoco"
        assert stored.scheduled_start == fixture["available_start"]
        assert stored.scheduled_end == fixture["available_start"] + timedelta(minutes=60)
    finally:
        _cleanup_reschedule_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t093c_replaces_an_eligible_reminder_once_without_duplicates(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reschedule_fixture(migrated_engine)
    service = _rescheduler(migrated_engine, fixture["now"])
    try:
        command = _command(fixture, fixture["available_start"])
        service.execute(command)
        service.execute(command)

        with migrated_engine.connect() as connection:
            reminders = connection.execute(
                select(
                    AppointmentReminder.appointment_scheduled_start,
                    AppointmentReminder.send_at,
                    AppointmentReminder.status,
                )
                .where(
                    AppointmentReminder.appointment_id == fixture["appointment_id"]
                )
                .order_by(AppointmentReminder.appointment_scheduled_start)
            ).all()

        assert reminders == [
            (
                fixture["original_start"],
                fixture["original_start"] - timedelta(hours=24),  # type: ignore[operator]
                "invalidated",
            ),
            (
                fixture["available_start"],
                fixture["available_start"] - timedelta(hours=24),  # type: ignore[operator]
                "scheduled",
            ),
        ]
    finally:
        _cleanup_reschedule_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t093c_invalidates_without_replacement_at_the_24_hour_boundary(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reschedule_fixture(migrated_engine)
    try:
        _rescheduler(migrated_engine, fixture["now"]).execute(
            _command(fixture, fixture["ineligible_start"]),
        )

        with migrated_engine.connect() as connection:
            reminders = connection.execute(
                select(
                    AppointmentReminder.appointment_scheduled_start,
                    AppointmentReminder.status,
                ).where(
                    AppointmentReminder.appointment_id == fixture["appointment_id"]
                )
            ).all()

        assert reminders == [(fixture["original_start"], "invalidated")]
    finally:
        _cleanup_reschedule_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t075_schedule_conflict_preserves_the_original_appointment(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reschedule_fixture(migrated_engine)
    try:
        with pytest.raises(PublicAppointmentRescheduleConflictError):
            _rescheduler(migrated_engine, fixture["now"]).execute(
                _command(fixture, fixture["blocked_start"]),
            )

        _assert_original_schedule(migrated_engine, fixture)
    finally:
        _cleanup_reschedule_fixture(migrated_engine, fixture)


class SyntheticPostUpdateFailure(RuntimeError):
    """Controlled failure raised after PostgreSQL receives the schedule update."""


class FailingAfterUpdateRepository(PostgresPublicAppointmentRescheduleRepository):
    def update_schedule(self, **values: object) -> bool:
        super().update_schedule(**values)  # type: ignore[arg-type]
        raise SyntheticPostUpdateFailure("synthetic post-update failure")


class FailingAfterUpdateUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentRescheduleRepository]:
        with self._engine.begin() as connection:
            yield FailingAfterUpdateRepository(connection)


class SyntheticPostReminderFailure(RuntimeError):
    """Controlled failure after reminder replacement but before commit."""


class FailingAfterReminderRepository(PostgresPublicAppointmentRescheduleRepository):
    def create_pending_deliveries(
        self,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> tuple[object, object]:
        raise SyntheticPostReminderFailure("synthetic post-reminder failure")


class FailingAfterReminderUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentRescheduleRepository]:
        with self._engine.begin() as connection:
            yield FailingAfterReminderRepository(connection)


@pytest.mark.integration
def test_t075_rolls_back_a_schedule_update_after_a_transaction_failure(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reschedule_fixture(migrated_engine)
    service = ReschedulePublicAppointment(
        unit_of_work=FailingAfterUpdateUnitOfWork(migrated_engine),
        clock=FixedClock(fixture["now"]),
    )
    try:
        with pytest.raises(SyntheticPostUpdateFailure):
            service.execute(_command(fixture, fixture["available_start"]))

        _assert_original_schedule(migrated_engine, fixture)
    finally:
        _cleanup_reschedule_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t093c_rolls_back_schedule_and_reminders_after_a_later_failure(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reschedule_fixture(migrated_engine)
    service = ReschedulePublicAppointment(
        unit_of_work=FailingAfterReminderUnitOfWork(migrated_engine),
        clock=FixedClock(fixture["now"]),
    )
    try:
        with pytest.raises(SyntheticPostReminderFailure):
            service.execute(_command(fixture, fixture["available_start"]))

        _assert_original_schedule(migrated_engine, fixture)
        with migrated_engine.connect() as connection:
            reminders = connection.execute(
                select(
                    AppointmentReminder.appointment_scheduled_start,
                    AppointmentReminder.status,
                ).where(
                    AppointmentReminder.appointment_id == fixture["appointment_id"]
                )
            ).all()
        assert reminders == [(fixture["original_start"], "scheduled")]
    finally:
        _cleanup_reschedule_fixture(migrated_engine, fixture)


def _rescheduler(engine: Engine, current_time: datetime) -> ReschedulePublicAppointment:
    return ReschedulePublicAppointment(
        unit_of_work=PostgresPublicAppointmentRescheduleUnitOfWork(engine),
        clock=FixedClock(current_time),
    )


def _command(
    fixture: dict[str, object],
    scheduled_start: datetime,
    *,
    service_name: str | None = None,
) -> PublicAppointmentRescheduleCommand:
    return PublicAppointmentRescheduleCommand(
        private_code_digest=fixture["private_code_digest"],  # type: ignore[arg-type]
        phone="55 1000 0000",
        service_name=(
            service_name
            if service_name is not None
            else fixture["target_service_name"]  # type: ignore[arg-type]
        ),
        branch="texcoco",
        scheduled_start=scheduled_start,
    )


def _seed_reschedule_fixture(engine: Engine) -> dict[str, object]:
    marker = uuid4().hex
    business_date = _unused_business_date(engine)
    now = datetime.combine(
        business_date - timedelta(days=1),
        time(hour=9),
        tzinfo=BUSINESS_TIME_ZONE,
    )
    original_start = datetime.combine(
        business_date,
        time(hour=10),
        tzinfo=BUSINESS_TIME_ZONE,
    )
    available_start = datetime.combine(
        business_date,
        time(hour=12),
        tzinfo=BUSINESS_TIME_ZONE,
    )
    ineligible_start = datetime.combine(
        business_date,
        time(hour=9),
        tzinfo=BUSINESS_TIME_ZONE,
    )
    blocked_start = datetime.combine(
        business_date,
        time(hour=15),
        tzinfo=BUSINESS_TIME_ZONE,
    )
    private_code_digest = f"synthetic-reschedule-{marker}".encode("ascii")
    private_code_ciphertext = b"synthetic-ciphertext"
    original_service_name = f"Servicio original {marker}"
    target_service_name = f"Servicio destino {marker}"

    with engine.begin() as connection:
        privacy_notice_version_id = connection.execute(
            PrivacyNoticeVersion.__table__.insert()
            .values(
                version=f"synthetic-reschedule-{marker}",
                content="Synthetic privacy notice for an integration test.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()
        original_service_id = connection.execute(
            Service.__table__.insert()
            .values(
                name=original_service_name,
                description="Synthetic original service.",
                duration_minutes=60,
                price=350,
                is_active=True,
                available_chiconcuac=True,
                available_texcoco=True,
            )
            .returning(Service.service_id)
        ).scalar_one()
        target_service_id = connection.execute(
            Service.__table__.insert()
            .values(
                name=target_service_name,
                description="Synthetic target service.",
                duration_minutes=90,
                price=450,
                is_active=True,
                available_chiconcuac=True,
                available_texcoco=True,
            )
            .returning(Service.service_id)
        ).scalar_one()
        appointment_id = connection.execute(
            Appointment.__table__.insert()
            .values(
                **_appointment_values(
                    private_code_digest=private_code_digest,
                    private_code_ciphertext=private_code_ciphertext,
                    service_id=original_service_id,
                    service_name=original_service_name,
                    scheduled_start=original_start,
                    privacy_notice_version_id=privacy_notice_version_id,
                    accepted_at=now,
                )
            )
            .returning(Appointment.appointment_id)
        ).scalar_one()
        connection.execute(
            AppointmentReminder.__table__.insert().values(
                appointment_id=appointment_id,
                appointment_scheduled_start=original_start,
                send_at=original_start - timedelta(hours=24),
                status="scheduled",
                status_changed_at=now,
                claimed_at=None,
                claim_expires_at=None,
            )
        )
        blocker_id = connection.execute(
            Appointment.__table__.insert()
            .values(
                **_appointment_values(
                    private_code_digest=f"synthetic-blocker-{marker}".encode("ascii"),
                    private_code_ciphertext=private_code_ciphertext,
                    service_id=original_service_id,
                    service_name=original_service_name,
                    scheduled_start=blocked_start,
                    privacy_notice_version_id=privacy_notice_version_id,
                    accepted_at=now,
                )
            )
            .returning(Appointment.appointment_id)
        ).scalar_one()

    return {
        "now": now,
        "private_code_digest": private_code_digest,
        "private_code_ciphertext": private_code_ciphertext,
        "original_start": original_start,
        "available_start": available_start,
        "ineligible_start": ineligible_start,
        "blocked_start": blocked_start,
        "appointment_id": appointment_id,
        "blocker_id": blocker_id,
        "original_service_id": original_service_id,
        "original_service_name": original_service_name,
        "target_service_id": target_service_id,
        "target_service_name": target_service_name,
        "privacy_notice_version_id": privacy_notice_version_id,
    }


def _appointment_values(
    *,
    private_code_digest: bytes,
    private_code_ciphertext: bytes,
    service_id: int,
    service_name: str,
    scheduled_start: datetime,
    privacy_notice_version_id: int,
    accepted_at: datetime,
) -> dict[str, object]:
    return {
        "private_code_ciphertext": private_code_ciphertext,
        "private_code_digest": private_code_digest,
        "first_name": "Clienta",
        "last_name": "Sintética",
        "phone": "5510000000",
        "email": "clienta@example.test",
        "service_id": service_id,
        "service_snapshot_name": service_name,
        "service_snapshot_duration_minutes": 60,
        "service_snapshot_price": 350,
        "branch": "chiconcuac",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_start + timedelta(hours=1),
        "status": "scheduled",
        "cancellation_reason": None,
        "origin": "public",
        "created_by_account_id": None,
        "privacy_notice_version_id": privacy_notice_version_id,
        "privacy_notice_accepted_at": accepted_at,
        "contact_processing_authorized": True,
        "adult_responsibility_declared": True,
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


def _assert_original_schedule(engine: Engine, fixture: dict[str, object]) -> None:
    with engine.connect() as connection:
        stored = connection.execute(
            select(
                Appointment.service_id,
                Appointment.branch,
                Appointment.scheduled_start,
                Appointment.scheduled_end,
            ).where(Appointment.appointment_id == fixture["appointment_id"])
        ).one()
    assert stored.service_id == fixture["original_service_id"]
    assert stored.branch == "chiconcuac"
    assert stored.scheduled_start == fixture["original_start"]
    assert stored.scheduled_end == fixture["original_start"] + timedelta(hours=1)


def _cleanup_reschedule_fixture(engine: Engine, fixture: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(Appointment).where(
                Appointment.appointment_id.in_(
                    (fixture["appointment_id"], fixture["blocker_id"]),
                )
            )
        )
        connection.execute(
            delete(Service).where(
                Service.service_id.in_(
                    (fixture["original_service_id"], fixture["target_service_id"]),
                )
            )
        )
        connection.execute(
            delete(PrivacyNoticeVersion).where(
                PrivacyNoticeVersion.privacy_notice_version_id
                == fixture["privacy_notice_version_id"]
            )
        )
