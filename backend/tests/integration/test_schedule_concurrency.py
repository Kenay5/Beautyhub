"""PostgreSQL integration coverage for concurrent agenda reservations."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, select, update

from backend.app.domain.schedule import (
    ScheduledInterval,
    TimeInterval,
    has_neighbor_separation_conflict,
    has_schedule_conflict,
    occupying_intervals,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    Appointment,
    PrivacyNoticeVersion,
    Service,
)
from backend.app.infrastructure.persistence.schedule_repository import (
    PostgresScheduleRepository,
)
from backend.app.infrastructure.persistence.service_repository import (
    PostgresServiceStatusRepository,
)
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BUSINESS_TIMEZONE = ZoneInfo("America/Mexico_City")


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
def test_concurrent_incompatible_reservations_commit_only_one(
    migrated_engine: Engine,
) -> None:
    marker = uuid4().hex
    with migrated_engine.begin() as connection:
        service_id = connection.execute(
            Service.__table__.insert()
            .values(
                name=f"Servicio concurrencia {marker}",
                description="Synthetic test service",
                duration_minutes=60,
                price=350,
                is_active=True,
                available_chiconcuac=True,
                available_texcoco=True,
            )
            .returning(Service.service_id)
        ).scalar_one()
        now = datetime.now(tz=BUSINESS_TIMEZONE)
        privacy_notice_version_id = connection.execute(
            PrivacyNoticeVersion.__table__.insert()
            .values(
                version=f"synthetic-concurrency-{marker}",
                content="Synthetic privacy notice for an integration test.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()

    scheduled_start = _unused_future_start(migrated_engine)
    scheduled_end = scheduled_start + timedelta(hours=1)
    barrier = Barrier(2)

    def reserve(branch: str, attempt_marker: str) -> bool:
        barrier.wait(timeout=10)
        with migrated_engine.connect() as connection:
            with connection.begin():
                schedule_repository = PostgresScheduleRepository(connection)
                schedule_repository.lock_schedule()
                candidate = ScheduledInterval(
                    interval=TimeInterval(scheduled_start, scheduled_end),
                    branch=branch,
                )
                occupied = occupying_intervals(
                    schedule_repository.list_scheduled_intervals()
                )
                if has_schedule_conflict(candidate.interval, occupied):
                    return False

                connection.execute(
                    Appointment.__table__.insert().values(
                        private_code_ciphertext=b"synthetic-ciphertext",
                        private_code_digest=f"synthetic-{attempt_marker}".encode(),
                        first_name="Clienta",
                        last_name="De Prueba",
                        phone="5510000000",
                        email="clienta@example.test",
                        service_id=service_id,
                        service_snapshot_name=f"Servicio concurrencia {marker}",
                        service_snapshot_duration_minutes=60,
                        service_snapshot_price=350,
                        branch=branch,
                        scheduled_start=scheduled_start,
                        scheduled_end=scheduled_end,
                        status="scheduled",
                        cancellation_reason=None,
                        origin="public",
                        created_by_account_id=None,
                        privacy_notice_version_id=privacy_notice_version_id,
                        privacy_notice_accepted_at=now,
                        contact_processing_authorized=True,
                        adult_responsibility_declared=True,
                    )
                )
                return True

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(
                future.result(timeout=20)
                for future in (
                    executor.submit(reserve, "chiconcuac", "attempt-a"),
                    executor.submit(reserve, "texcoco", "attempt-b"),
                )
            )

        assert sum(outcomes) == 1
        with migrated_engine.connect() as connection:
            committed_reservations = connection.execute(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.scheduled_start == scheduled_start,
                    Appointment.status == "scheduled",
                    Appointment.service_id == service_id,
                )
            ).scalar_one()
        assert committed_reservations == 1
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(
                delete(Appointment).where(Appointment.service_id == service_id)
            )
            connection.execute(delete(Service).where(Service.service_id == service_id))
            connection.execute(
                delete(PrivacyNoticeVersion).where(
                    PrivacyNoticeVersion.privacy_notice_version_id
                    == privacy_notice_version_id
                )
            )


@pytest.mark.integration
def test_concurrent_reschedule_and_service_deactivation_leave_a_valid_appointment(
    migrated_engine: Engine,
) -> None:
    marker = uuid4().hex
    with migrated_engine.begin() as connection:
        service_id = connection.execute(
            Service.__table__.insert()
            .values(
                name=f"Servicio vigencia {marker}",
                description="Synthetic test service",
                duration_minutes=60,
                price=350,
                is_active=True,
                available_chiconcuac=True,
                available_texcoco=True,
            )
            .returning(Service.service_id)
        ).scalar_one()
        now = datetime.now(tz=BUSINESS_TIMEZONE)
        privacy_notice_version_id = connection.execute(
            PrivacyNoticeVersion.__table__.insert()
            .values(
                version=f"synthetic-service-status-{marker}",
                content="Synthetic privacy notice for an integration test.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()

    original_start = _unused_future_start(migrated_engine, hour=11)
    original_end = original_start + timedelta(hours=1)
    with migrated_engine.begin() as connection:
        appointment_id = connection.execute(
            Appointment.__table__.insert()
            .values(
                private_code_ciphertext=b"synthetic-ciphertext",
                private_code_digest=f"synthetic-move-{marker}".encode(),
                first_name="Clienta",
                last_name="De Prueba",
                phone="5510000000",
                email="clienta@example.test",
                service_id=service_id,
                service_snapshot_name=f"Servicio vigencia {marker}",
                service_snapshot_duration_minutes=60,
                service_snapshot_price=350,
                branch="chiconcuac",
                scheduled_start=original_start,
                scheduled_end=original_end,
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

    moved_start = _unused_future_start(migrated_engine, hour=15)
    moved_end = moved_start + timedelta(hours=1)
    barrier = Barrier(2)

    def reschedule() -> bool:
        barrier.wait(timeout=10)
        with migrated_engine.connect() as connection:
            with connection.begin():
                schedule_repository = PostgresScheduleRepository(connection)
                schedule_repository.lock_schedule()
                service_is_active = connection.execute(
                    select(Service.is_active).where(Service.service_id == service_id)
                ).scalar_one()
                if not service_is_active:
                    return False

                candidate = ScheduledInterval(
                    interval=TimeInterval(moved_start, moved_end),
                    branch="chiconcuac",
                )
                scheduled_intervals = tuple(
                    scheduled_interval
                    for scheduled_interval in schedule_repository.list_scheduled_intervals()
                    if scheduled_interval.interval
                    != TimeInterval(original_start, original_end)
                )
                if _has_candidate_schedule_conflict(candidate, scheduled_intervals):
                    return False

                result = connection.execute(
                    update(Appointment)
                    .where(
                        Appointment.appointment_id == appointment_id,
                        Appointment.status == "scheduled",
                    )
                    .values(
                        scheduled_start=moved_start,
                        scheduled_end=moved_end,
                    )
                )
                return result.rowcount == 1

    def deactivate_service() -> bool:
        barrier.wait(timeout=10)
        with migrated_engine.connect() as connection:
            with connection.begin():
                return PostgresServiceStatusRepository(connection).set_service_active(
                    service_id,
                    False,
                )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            move_outcome, deactivation_outcome = tuple(
                future.result(timeout=20)
                for future in (
                    executor.submit(reschedule),
                    executor.submit(deactivate_service),
                )
            )

        assert deactivation_outcome is True
        with migrated_engine.connect() as connection:
            appointment = connection.execute(
                select(
                    Appointment.scheduled_start,
                    Appointment.scheduled_end,
                    Appointment.service_snapshot_name,
                    Appointment.status,
                ).where(Appointment.appointment_id == appointment_id)
            ).one()
            service_is_active = connection.execute(
                select(Service.is_active).where(Service.service_id == service_id)
            ).scalar_one()

        assert service_is_active is False
        assert appointment.status == "scheduled"
        assert appointment.service_snapshot_name == f"Servicio vigencia {marker}"
        if move_outcome:
            assert (appointment.scheduled_start, appointment.scheduled_end) == (
                moved_start,
                moved_end,
            )
        else:
            assert (appointment.scheduled_start, appointment.scheduled_end) == (
                original_start,
                original_end,
            )
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(
                delete(Appointment).where(Appointment.appointment_id == appointment_id)
            )
            connection.execute(delete(Service).where(Service.service_id == service_id))
            connection.execute(
                delete(PrivacyNoticeVersion).where(
                    PrivacyNoticeVersion.privacy_notice_version_id
                    == privacy_notice_version_id
                )
            )


def _unused_future_start(engine: Engine, hour: int = 11) -> datetime:
    """Choose an unoccupied business-hour slot within the approved horizon."""

    today = datetime.now(tz=BUSINESS_TIMEZONE).date()
    for day_offset in range(80, 90):
        candidate = datetime.combine(
            today + timedelta(days=day_offset),
            time(hour=hour),
            tzinfo=BUSINESS_TIMEZONE,
        )
        with engine.connect() as connection:
            intervals = tuple(
                ScheduledInterval(
                    interval=TimeInterval(row.scheduled_start, row.scheduled_end),
                    branch=row.branch,
                    status=row.status,
                )
                for row in connection.execute(
                    select(
                        Appointment.scheduled_start,
                        Appointment.scheduled_end,
                        Appointment.branch,
                        Appointment.status,
                    ).where(Appointment.status == "scheduled")
                )
            )
        candidate_interval = ScheduledInterval(
            interval=TimeInterval(candidate, candidate + timedelta(hours=1)),
            branch="chiconcuac",
        )
        if not _has_candidate_schedule_conflict(candidate_interval, intervals):
            return candidate
    raise AssertionError("No unused synthetic appointment slot was found.")


def _has_candidate_schedule_conflict(
    candidate: ScheduledInterval,
    scheduled_intervals: tuple[ScheduledInterval, ...],
) -> bool:
    """Apply overlap and adjacent-appointment buffers to a test candidate."""

    if has_schedule_conflict(candidate.interval, occupying_intervals(scheduled_intervals)):
        return True

    previous = max(
        (
            scheduled_interval
            for scheduled_interval in scheduled_intervals
            if scheduled_interval.interval.end <= candidate.interval.start
        ),
        key=lambda scheduled_interval: scheduled_interval.interval.end,
        default=None,
    )
    following = min(
        (
            scheduled_interval
            for scheduled_interval in scheduled_intervals
            if scheduled_interval.interval.start >= candidate.interval.end
        ),
        key=lambda scheduled_interval: scheduled_interval.interval.start,
        default=None,
    )
    return has_neighbor_separation_conflict(candidate, previous, following)
