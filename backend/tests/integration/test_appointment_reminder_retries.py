"""T093G PostgreSQL evidence for bounded manual reminder retries."""

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
from sqlalchemy import Engine, delete, insert, select, update

from backend.app.application.clock import FixedClock
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.retry_failed_appointment_reminder import (
    AdministrativeReminderRetryActor,
    AppointmentReminderRetryNotPermittedError,
    RetryFailedAppointmentReminder,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.appointment_reminder_retry_repository import (
    PostgresAppointmentReminderRetryUnitOfWork,
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
def test_t093g_persists_a_distinct_retry_for_the_current_contact_only(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_failed_reminder_delivery(migrated_engine)
    updated_email = "actualizado@example.test"
    with migrated_engine.begin() as connection:
        connection.execute(
            update(Appointment)
            .where(Appointment.appointment_id == fixture["appointment_id"])
            .values(email=updated_email)
        )
    email = EmailSimulator(outcome="accepted")
    service = _retry_service(migrated_engine, fixture, email=email)
    try:
        before = _appointment_state(migrated_engine, fixture)

        result = service.execute(actor=_actor(), delivery_id=fixture["delivery_id"])

        assert result.previous_delivery_id == fixture["delivery_id"]
        assert result.channel == "email"
        assert result.status == "accepted"
        assert [notification.recipient for notification in email.notifications] == [
            updated_email
        ]
        assert _appointment_state(migrated_engine, fixture) == before
        assert _delivery_chain(migrated_engine, fixture) == [
            (fixture["delivery_id"], None, "failed", fixture["reminder_id"]),
            (result.delivery_id, fixture["delivery_id"], "accepted", None),
        ]
    finally:
        _cleanup(migrated_engine, fixture)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("remaining", "expected"),
    (
        pytest.param(timedelta(minutes=60, seconds=1), "accepted", id="over-60"),
        pytest.param(timedelta(minutes=60), "rejected", id="exactly-60"),
        pytest.param(timedelta(minutes=59, seconds=59), "rejected", id="under-60"),
    ),
)
def test_t093g_enforces_the_exact_sixty_minute_boundary_in_postgresql(
    migrated_engine: Engine,
    remaining: timedelta,
    expected: str,
) -> None:
    fixture = _seed_failed_reminder_delivery(
        migrated_engine,
        remaining=remaining,
    )
    try:
        if expected == "accepted":
            _retry_service(migrated_engine, fixture).execute(
                actor=_actor(),
                delivery_id=fixture["delivery_id"],
            )
            assert len(_delivery_chain(migrated_engine, fixture)) == 2
        else:
            with pytest.raises(AppointmentReminderRetryNotPermittedError):
                _retry_service(migrated_engine, fixture).execute(
                    actor=_actor(),
                    delivery_id=fixture["delivery_id"],
                )
            assert len(_delivery_chain(migrated_engine, fixture)) == 1
    finally:
        _cleanup(migrated_engine, fixture)


@pytest.mark.integration
def test_t093g_accepts_the_exact_five_minute_retry_boundary(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_failed_reminder_delivery(migrated_engine)
    try:
        exact_delivery_id = _append_failed_retry(
            migrated_engine,
            fixture,
            previous_delivery_id=fixture["delivery_id"],
            attempted_at=fixture["now"] - timedelta(minutes=5),
        )
        _retry_service(migrated_engine, fixture).execute(
            actor=_actor(),
            delivery_id=exact_delivery_id,
        )
        assert len(_delivery_chain(migrated_engine, fixture)) == 3
    finally:
        _cleanup(migrated_engine, fixture)


@pytest.mark.integration
def test_t093g_rejects_a_fourth_retry_for_the_same_reminder_channel(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_failed_reminder_delivery(migrated_engine)
    try:
        first_retry_id = _append_failed_retry(
            migrated_engine,
            fixture,
            previous_delivery_id=fixture["delivery_id"],
            attempted_at=fixture["now"] - timedelta(minutes=15),
        )
        second_retry_id = _append_failed_retry(
            migrated_engine,
            fixture,
            previous_delivery_id=first_retry_id,
            attempted_at=fixture["now"] - timedelta(minutes=10),
        )
        third_retry_id = _append_failed_retry(
            migrated_engine,
            fixture,
            previous_delivery_id=second_retry_id,
            attempted_at=fixture["now"] - timedelta(minutes=5),
        )

        with pytest.raises(AppointmentReminderRetryNotPermittedError):
            _retry_service(migrated_engine, fixture).execute(
                actor=_actor(),
                delivery_id=third_retry_id,
            )
        assert len(_delivery_chain(migrated_engine, fixture)) == 4
    finally:
        _cleanup(migrated_engine, fixture)


@pytest.mark.integration
def test_t093g_concurrent_requests_create_at_most_one_retry_for_a_channel(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_failed_reminder_delivery(migrated_engine)
    barrier = Barrier(2)
    try:
        def retry() -> str:
            barrier.wait(timeout=10)
            try:
                _retry_service(migrated_engine, fixture).execute(
                    actor=_actor(),
                    delivery_id=fixture["delivery_id"],
                )
            except AppointmentReminderRetryNotPermittedError:
                return "rejected"
            return "created"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                future.result(timeout=20)
                for future in (executor.submit(retry), executor.submit(retry))
            )

        assert sorted(results) == ["created", "rejected"]
        assert len(_delivery_chain(migrated_engine, fixture)) == 2
    finally:
        _cleanup(migrated_engine, fixture)


class AllowAdministrativeRetry:
    def ensure_allowed(self, actor: AdministrativeReminderRetryActor) -> None:
        assert actor.role in {"owner", "staff"}


class AllowAppointmentNotificationActions:
    def ensure_allowed(self, *, account_id: int) -> None:
        assert account_id > 0


def _retry_service(
    engine: Engine,
    fixture: dict[str, object],
    *,
    email: EmailSimulator | None = None,
) -> RetryFailedAppointmentReminder:
    return RetryFailedAppointmentReminder(
        authorizer=AllowAdministrativeRetry(),
        limiter=AllowAppointmentNotificationActions(),
        unit_of_work=PostgresAppointmentReminderRetryUnitOfWork(engine),
        dispatcher=NotificationDispatcher(
            email_port=email or EmailSimulator(outcome="accepted"),
            whatsapp_port=WhatsAppSimulator(outcome="accepted"),
            result_writer=PostgresNotificationDeliveryResultWriter(engine),
        ),
        clock=FixedClock(fixture["now"]),  # type: ignore[arg-type]
    )


def _actor() -> AdministrativeReminderRetryActor:
    return AdministrativeReminderRetryActor(account_id=7, role="staff")


def _seed_failed_reminder_delivery(
    engine: Engine,
    *,
    remaining: timedelta = timedelta(hours=2),
) -> dict[str, object]:
    marker = uuid4().hex
    now = datetime.now(tz=BUSINESS_TIME_ZONE).replace(microsecond=0)
    scheduled_start = now + remaining
    private_code_digest = f"synthetic-reminder-retry-{marker}".encode("ascii")
    with engine.begin() as connection:
        privacy_notice_version_id = connection.execute(
            insert(PrivacyNoticeVersion)
            .values(
                version=f"synthetic-reminder-retry-{marker}",
                content="Synthetic privacy notice for reminder retry testing.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()
        service_id = connection.execute(
            insert(Service)
            .values(
                name=f"Servicio reintento recordatorio {marker}",
                description="Synthetic reminder retry service.",
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
                service_snapshot_name=f"Servicio reintento recordatorio {marker}",
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
                status="completed",
                status_changed_at=now,
                claimed_at=None,
                claim_expires_at=None,
            )
            .returning(AppointmentReminder.appointment_reminder_id)
        ).scalar_one()
        delivery_id = connection.execute(
            insert(NotificationDelivery)
            .values(
                appointment_id=appointment_id,
                appointment_reminder_id=reminder_id,
                event="appointment_reminder",
                channel="email",
                status="failed",
                status_changed_at=now,
                sanitized_error="notification delivery failed.",
                created_at=now,
                updated_at=now,
            )
            .returning(NotificationDelivery.notification_delivery_id)
        ).scalar_one()
    return {
        "now": now,
        "appointment_id": appointment_id,
        "reminder_id": reminder_id,
        "delivery_id": delivery_id,
        "service_id": service_id,
        "privacy_notice_version_id": privacy_notice_version_id,
    }


def _append_failed_retry(
    engine: Engine,
    fixture: dict[str, object],
    *,
    previous_delivery_id: int,
    attempted_at: datetime,
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            insert(NotificationDelivery)
            .values(
                appointment_id=fixture["appointment_id"],
                appointment_reminder_id=None,
                event="appointment_reminder",
                channel="email",
                status="failed",
                status_changed_at=attempted_at,
                previous_delivery_id=previous_delivery_id,
                sanitized_error="notification delivery failed.",
                created_at=attempted_at,
                updated_at=attempted_at,
            )
            .returning(NotificationDelivery.notification_delivery_id)
        ).scalar_one()


def _appointment_state(engine: Engine, fixture: dict[str, object]):
    with engine.connect() as connection:
        return connection.execute(
            select(
                Appointment.status,
                Appointment.scheduled_start,
                Appointment.scheduled_end,
                Appointment.branch,
                Appointment.service_snapshot_name,
                Appointment.phone,
                Appointment.email,
            ).where(Appointment.appointment_id == fixture["appointment_id"])
        ).one()


def _delivery_chain(engine: Engine, fixture: dict[str, object]):
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                NotificationDelivery.notification_delivery_id,
                NotificationDelivery.previous_delivery_id,
                NotificationDelivery.status,
                NotificationDelivery.appointment_reminder_id,
            )
            .where(NotificationDelivery.appointment_id == fixture["appointment_id"])
            .order_by(NotificationDelivery.notification_delivery_id)
        ).all()
    return [
        (
            row.notification_delivery_id,
            row.previous_delivery_id,
            row.status,
            row.appointment_reminder_id,
        )
        for row in rows
    ]


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
