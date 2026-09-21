"""T093E PostgreSQL evidence for durable concurrent reminder claims."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, insert, select

from backend.app.application.claim_due_appointment_reminder import (
    ClaimDueAppointmentReminder,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.persistence.appointment_reminder_claim_repository import (
    PostgresDueAppointmentReminderClaimUnitOfWork,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    PrivacyNoticeVersion,
    Service,
)
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CLAIM_LEASE = timedelta(minutes=5)


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
def test_t093e_concurrent_processes_claim_one_due_reminder_only_once(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reminder(migrated_engine, remaining=timedelta(hours=2))
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=10)
        return _claimer(migrated_engine, fixture["now"]).execute()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                future.result(timeout=20)
                for future in (executor.submit(claim), executor.submit(claim))
            )

        claimed = [result for result in results if result is not None]
        assert len(claimed) == 1
        assert claimed[0].outcome == "claimed"
        with migrated_engine.connect() as connection:
            stored = connection.execute(
                select(
                    AppointmentReminder.status,
                    AppointmentReminder.claimed_at,
                    AppointmentReminder.claim_expires_at,
                ).where(
                    AppointmentReminder.appointment_reminder_id
                    == fixture["reminder_id"]
                )
            ).one()
            reminder_count = connection.execute(
                select(func.count())
                .select_from(AppointmentReminder)
                .where(AppointmentReminder.appointment_id == fixture["appointment_id"])
            ).scalar_one()

        assert stored.status == "claimed"
        assert stored.claimed_at == fixture["now"]
        assert stored.claim_expires_at == fixture["now"] + CLAIM_LEASE
        assert reminder_count == 1
    finally:
        _cleanup_reminder(migrated_engine, fixture)


@pytest.mark.integration
def test_t093e_recovers_an_abandoned_claim_at_its_exact_expiration(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_reminder(
        migrated_engine,
        remaining=timedelta(hours=2),
        status="claimed",
        claimed_at_offset=timedelta(minutes=-10),
        claim_expires_at_offset=timedelta(),
    )
    try:
        result = _claimer(migrated_engine, fixture["now"]).execute()

        assert result is not None
        assert result.outcome == "claimed"
        assert result.claimed_at == fixture["now"]
        assert result.claim_expires_at == fixture["now"] + CLAIM_LEASE
    finally:
        _cleanup_reminder(migrated_engine, fixture)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("remaining", "expected_outcome", "expected_status"),
    (
        pytest.param(
            timedelta(minutes=60, seconds=1),
            "claimed",
            "claimed",
            id="over-60",
        ),
        pytest.param(
            timedelta(minutes=60),
            "omitted",
            "omitted",
            id="exactly-60",
        ),
        pytest.param(
            timedelta(minutes=59, seconds=59),
            "omitted",
            "omitted",
            id="under-60",
        ),
    ),
)
def test_t093e_persists_the_exact_processing_boundary(
    migrated_engine: Engine,
    remaining: timedelta,
    expected_outcome: str,
    expected_status: str,
) -> None:
    fixture = _seed_reminder(migrated_engine, remaining=remaining)
    try:
        result = _claimer(migrated_engine, fixture["now"]).execute()

        assert result is not None
        assert result.outcome == expected_outcome
        with migrated_engine.connect() as connection:
            stored = connection.execute(
                select(
                    AppointmentReminder.status,
                    AppointmentReminder.claimed_at,
                    AppointmentReminder.claim_expires_at,
                ).where(
                    AppointmentReminder.appointment_reminder_id
                    == fixture["reminder_id"]
                )
            ).one()
        assert stored.status == expected_status
        if expected_status == "omitted":
            assert stored.claimed_at is None
            assert stored.claim_expires_at is None
    finally:
        _cleanup_reminder(migrated_engine, fixture)


def _claimer(engine: Engine, now: object) -> ClaimDueAppointmentReminder:
    return ClaimDueAppointmentReminder(
        unit_of_work=PostgresDueAppointmentReminderClaimUnitOfWork(engine),
        clock=FixedClock(now),  # type: ignore[arg-type]
        claim_lease=CLAIM_LEASE,
    )


def _seed_reminder(
    engine: Engine,
    *,
    remaining: timedelta,
    status: str = "scheduled",
    claimed_at_offset: timedelta | None = None,
    claim_expires_at_offset: timedelta | None = None,
) -> dict[str, object]:
    marker = uuid4().hex
    now = datetime.now(tz=BUSINESS_TIME_ZONE).replace(microsecond=0)
    scheduled_start = now + remaining
    claimed_at = (
        now + claimed_at_offset if claimed_at_offset is not None else None
    )
    claim_expires_at = (
        now + claim_expires_at_offset
        if claim_expires_at_offset is not None
        else None
    )
    with engine.begin() as connection:
        privacy_notice_version_id = connection.execute(
            insert(PrivacyNoticeVersion)
            .values(
                version=f"synthetic-reminder-{marker}",
                content="Synthetic privacy notice for reminder testing.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()
        service_id = connection.execute(
            insert(Service)
            .values(
                name=f"Servicio recordatorio {marker}",
                description="Synthetic reminder service.",
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
                private_code_digest=f"synthetic-reminder-{marker}".encode("ascii"),
                first_name="Clienta",
                last_name="Sintética",
                phone="5510000000",
                email="clienta@example.test",
                service_id=service_id,
                service_snapshot_name=f"Servicio recordatorio {marker}",
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
                status=status,
                status_changed_at=claimed_at or now,
                claimed_at=claimed_at,
                claim_expires_at=claim_expires_at,
            )
            .returning(AppointmentReminder.appointment_reminder_id)
        ).scalar_one()
    return {
        "now": now,
        "appointment_id": appointment_id,
        "reminder_id": reminder_id,
        "service_id": service_id,
        "privacy_notice_version_id": privacy_notice_version_id,
    }


def _cleanup_reminder(engine: Engine, fixture: dict[str, object]) -> None:
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
