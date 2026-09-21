"""T052 PostgreSQL integration tests for atomic appointment confirmation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, insert, select

from backend.app.application.clock import FixedClock
from backend.app.application.confirm_appointment_with_notifications import (
    ConfirmAppointmentWithNotifications,
)
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.prepare_notification_retry import PrepareNotificationRetry
from backend.app.application.confirm_appointment import (
    AppointmentScheduleConflictError,
    ConfirmAppointment,
    ConfirmAppointmentCommand,
)
from backend.app.application.private_code import PrivateCode
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.privacy_consent import (
    ADMINISTRATIVE_APPOINTMENT_ORIGIN,
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.persistence.appointment_confirmation_repository import (
    PostgresAppointmentConfirmationRepository,
    PostgresAppointmentConfirmationUnitOfWork,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.notification_delivery_result_writer import (
    PostgresNotificationDeliveryResultWriter,
)
from backend.app.infrastructure.persistence.notification_retry_repository import (
    PostgresNotificationRetryUnitOfWork,
)
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    BookingConfirmationReference,
    NotificationDelivery,
    PrivacyNoticeVersion,
    Service,
)
from backend.app.infrastructure.settings import load_test_database_url
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class TestPrivateCodeProtection:
    """Deterministic in-memory double; production cryptography is tested separately."""

    _codes_by_ciphertext: dict[bytes, PrivateCode] = {}

    def digest(self, secret: str) -> bytes:
        return hashlib.sha256(f"lookup:{secret}".encode("ascii")).digest()

    def encrypt(self, private_code: PrivateCode) -> bytes:
        ciphertext = hashlib.sha256(
            f"cipher:{private_code.value}".encode("ascii")
        ).digest()
        self._codes_by_ciphertext[ciphertext] = private_code
        return ciphertext

    def decrypt(self, ciphertext: bytes) -> PrivateCode:
        return self._codes_by_ciphertext[ciphertext]


class SimulatedDeliveryIntentFailure(RuntimeError):
    pass


class FailingDeliveryRepository(PostgresAppointmentConfirmationRepository):
    def create_pending_deliveries(
        self,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> tuple[int, int]:
        self._connection.execute(
            insert(NotificationDelivery).values(
                appointment_id=appointment_id,
                event="appointment_created",
                channel="email",
                status="pending",
                status_changed_at=status_changed_at,
                external_reference=None,
                appointment_reminder_id=None,
                previous_delivery_id=None,
                sanitized_error=None,
            )
        )
        raise SimulatedDeliveryIntentFailure("synthetic failure")


class FailingDeliveryUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[FailingDeliveryRepository]:
        with self._engine.begin() as connection:
            yield FailingDeliveryRepository(connection)


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
def test_t052_commits_appointment_reference_and_two_pending_deliveries(
    migrated_engine: Engine,
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine)
    try:
        result = confirmation_service(migrated_engine, fixture["now"]).execute(
            confirmation_command(fixture, "success")
        )

        with migrated_engine.connect() as connection:
            appointment = connection.execute(
                select(
                    Appointment.service_snapshot_name,
                    Appointment.service_snapshot_duration_minutes,
                    Appointment.service_snapshot_price,
                ).where(
                    Appointment.appointment_id == result.appointment_id
                )
            ).one()
            deliveries = connection.execute(
                select(
                    NotificationDelivery.channel,
                    NotificationDelivery.status,
                    NotificationDelivery.event,
                )
                .where(NotificationDelivery.appointment_id == result.appointment_id)
                .order_by(NotificationDelivery.channel)
            ).all()
            reference = connection.execute(
                select(
                    BookingConfirmationReference.consumed_at,
                    BookingConfirmationReference.appointment_id,
                ).where(
                    BookingConfirmationReference.reference_digest
                    == fixture["reference_digests"][0]
                )
            ).one()

        assert appointment.service_snapshot_name == fixture["service_name"]
        assert appointment.service_snapshot_duration_minutes == 60
        assert appointment.service_snapshot_price == Decimal("350.00")
        assert [(row.channel, row.status, row.event) for row in deliveries] == [
            ("email", "pending", "appointment_created"),
            ("whatsapp", "pending", "appointment_created"),
        ]
        assert reference.consumed_at == fixture["now"]
        assert reference.appointment_id == result.appointment_id
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t093b_persists_one_initial_reminder_at_exactly_24_hours_before_start(
    migrated_engine: Engine,
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine)
    try:
        service = confirmation_service(migrated_engine, fixture["now"])
        result = service.execute(
            confirmation_command(fixture, "initial-reminder")
        )
        retry = service.execute(confirmation_command(fixture, "ignored-retry"))

        with migrated_engine.connect() as connection:
            reminders = connection.execute(
                select(
                    AppointmentReminder.appointment_id,
                    AppointmentReminder.appointment_scheduled_start,
                    AppointmentReminder.send_at,
                    AppointmentReminder.status,
                    AppointmentReminder.status_changed_at,
                ).where(AppointmentReminder.appointment_id == result.appointment_id)
            ).all()

        assert reminders == [
            (
                result.appointment_id,
                fixture["scheduled_start"],
                fixture["scheduled_start"] - timedelta(hours=24),  # type: ignore[operator]
                "scheduled",
                fixture["now"],
            )
        ]
        assert retry.appointment_id == result.appointment_id
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("origin", "confirmed_by_account_id"),
    (
        pytest.param(PUBLIC_APPOINTMENT_ORIGIN, None, id="public"),
        pytest.param(ADMINISTRATIVE_APPOINTMENT_ORIGIN, 41, id="administrative"),
    ),
)
@pytest.mark.parametrize(
    ("notice", "expected_reminder_count"),
    (
        pytest.param(timedelta(hours=24, seconds=1), 1, id="over-24-hours"),
        pytest.param(timedelta(hours=24), 0, id="exactly-24-hours"),
        pytest.param(timedelta(hours=23, minutes=59, seconds=59), 0, id="under-24-hours"),
    ),
)
def test_t093h_postgresql_applies_the_exact_initial_reminder_boundary_to_both_origins(
    migrated_engine: Engine,
    origin: str,
    confirmed_by_account_id: int | None,
    notice: timedelta,
    expected_reminder_count: int,
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine, notice=notice)
    try:
        result = confirmation_service(migrated_engine, fixture["now"]).execute(
            confirmation_command(
                fixture,
                f"t093h-{origin}",
                origin=origin,
                confirmed_by_account_id=confirmed_by_account_id,
            )
        )

        with migrated_engine.connect() as connection:
            appointment_origin = connection.execute(
                select(Appointment.origin, Appointment.created_by_account_id).where(
                    Appointment.appointment_id == result.appointment_id
                )
            ).one()
            reminder_count = connection.execute(
                select(func.count())
                .select_from(AppointmentReminder)
                .where(AppointmentReminder.appointment_id == result.appointment_id)
            ).scalar_one()

        assert appointment_origin == (origin, confirmed_by_account_id)
        assert reminder_count == expected_reminder_count
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t052_rolls_back_appointment_and_first_delivery_when_second_step_fails(
    migrated_engine: Engine,
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine)
    service = ConfirmAppointment(
        unit_of_work=FailingDeliveryUnitOfWork(migrated_engine),
        clock=FixedClock(fixture["now"]),
        secret_generator=SequenceSecretGenerator([b"\x03" * 16]),
        private_code_protection=TestPrivateCodeProtection(),
    )
    try:
        with pytest.raises(SimulatedDeliveryIntentFailure):
            service.execute(confirmation_command(fixture, "rollback"))

        with migrated_engine.connect() as connection:
            appointment_count = connection.execute(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            delivery_count = connection.execute(
                select(func.count())
                .select_from(NotificationDelivery)
                .join(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            reminder_count = connection.execute(
                select(func.count())
                .select_from(AppointmentReminder)
                .join(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            reference = connection.execute(
                select(
                    BookingConfirmationReference.consumed_at,
                    BookingConfirmationReference.appointment_id,
                ).where(
                    BookingConfirmationReference.reference_digest
                    == fixture["reference_digests"][0]
                )
            ).one()

        assert appointment_count == 0
        assert delivery_count == 0
        assert reminder_count == 0
        assert reference.consumed_at is None
        assert reference.appointment_id is None
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t052_concurrent_incompatible_confirmations_leave_one_complete_result(
    migrated_engine: Engine,
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine, reference_count=2)
    barrier = Barrier(2)

    def confirm(attempt: int) -> bool:
        barrier.wait(timeout=10)
        try:
            confirmation_service(migrated_engine, fixture["now"]).execute(
                confirmation_command(fixture, f"race-{attempt}", attempt)
            )
            return True
        except AppointmentScheduleConflictError:
            return False

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(
                future.result(timeout=20)
                for future in (
                    executor.submit(confirm, 0),
                    executor.submit(confirm, 1),
                )
            )

        with migrated_engine.connect() as connection:
            appointment_count = connection.execute(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            delivery_count = connection.execute(
                select(func.count())
                .select_from(NotificationDelivery)
                .join(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            reminder_count = connection.execute(
                select(func.count())
                .select_from(AppointmentReminder)
                .join(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            consumed_reference_count = connection.execute(
                select(func.count())
                .select_from(BookingConfirmationReference)
                .where(
                    BookingConfirmationReference.reference_digest.in_(
                        fixture["reference_digests"]
                    ),
                    BookingConfirmationReference.consumed_at.is_not(None),
                )
            ).scalar_one()

        assert sum(outcomes) == 1
        assert appointment_count == 1
        assert delivery_count == 2
        assert reminder_count == 1
        assert consumed_reference_count == 1
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t053_retry_returns_same_appointment_code_and_original_deliveries(
    migrated_engine: Engine,
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine)
    service = confirmation_service(migrated_engine, fixture["now"])
    try:
        original = service.execute(confirmation_command(fixture, "original"))
        retry = service.execute(confirmation_command(fixture, "ignored-retry"))

        with migrated_engine.connect() as connection:
            appointment_count = connection.execute(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            delivery_count = connection.execute(
                select(func.count())
                .select_from(NotificationDelivery)
                .join(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            reminder_count = connection.execute(
                select(func.count())
                .select_from(AppointmentReminder)
                .join(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()

        assert retry.appointment_id == original.appointment_id
        assert retry.private_code == original.private_code
        assert retry.delivery_ids == original.delivery_ids
        assert retry.deliveries == original.deliveries
        assert appointment_count == 1
        assert delivery_count == 2
        assert reminder_count == 1
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("email_outcome", "whatsapp_outcome", "expected_statuses"),
    (
        ("accepted", "accepted", ("accepted", "accepted")),
        ("failed", "failed", ("failed", "failed")),
        ("failed", "accepted", ("failed", "accepted")),
    ),
)
def test_t092_retry_preserves_original_delivery_results_without_new_attempts(
    migrated_engine: Engine,
    email_outcome: str,
    whatsapp_outcome: str,
    expected_statuses: tuple[str, str],
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine)
    first_email = EmailSimulator(outcome=email_outcome)  # type: ignore[arg-type]
    first_whatsapp = WhatsAppSimulator(outcome=whatsapp_outcome)  # type: ignore[arg-type]
    try:
        original = confirmation_with_notifications(
            migrated_engine,
            fixture["now"],  # type: ignore[arg-type]
            email=first_email,
            whatsapp=first_whatsapp,
        ).execute(confirmation_command(fixture, "original"))
        retry_email = EmailSimulator(outcome="accepted")
        retry_whatsapp = WhatsAppSimulator(outcome="accepted")
        retry = confirmation_with_notifications(
            migrated_engine,
            fixture["now"],  # type: ignore[arg-type]
            email=retry_email,
            whatsapp=retry_whatsapp,
        ).execute(confirmation_command(fixture, "ignored-retry"))

        with migrated_engine.connect() as connection:
            deliveries = connection.execute(
                select(
                    NotificationDelivery.notification_delivery_id,
                    NotificationDelivery.channel,
                    NotificationDelivery.status,
                )
                .where(NotificationDelivery.appointment_id == original.appointment_id)
                .order_by(NotificationDelivery.channel)
            ).all()

        assert [delivery.status for delivery in original.deliveries] == list(
            expected_statuses
        )
        assert [delivery.status for delivery in retry.deliveries] == list(
            expected_statuses
        )
        assert retry.delivery_ids == original.delivery_ids
        assert len(first_email.notifications) == len(first_whatsapp.notifications) == 1
        assert not retry_email.notifications
        assert not retry_whatsapp.notifications
        assert [(row.channel, row.status) for row in deliveries] == [
            ("email", expected_statuses[0]),
            ("whatsapp", expected_statuses[1]),
        ]
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t093a_creates_a_linked_retry_at_the_current_contact_without_changing_appointment(
    migrated_engine: Engine,
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine)
    try:
        confirmed = confirmation_service(migrated_engine, fixture["now"]).execute(
            confirmation_command(fixture, "original")
        )
        original_delivery_id = confirmed.deliveries[0].delivery_id
        with migrated_engine.begin() as connection:
            connection.execute(
                NotificationDelivery.__table__.update()
                .where(NotificationDelivery.notification_delivery_id == original_delivery_id)
                .values(status="failed", sanitized_error="notification delivery failed.")
            )
            connection.execute(
                Appointment.__table__.update()
                .where(Appointment.appointment_id == confirmed.appointment_id)
                .values(email="current-contact@example.test")
            )
        with migrated_engine.connect() as connection:
            before = connection.execute(
                select(
                    Appointment.service_snapshot_name,
                    Appointment.scheduled_start,
                    Appointment.status,
                    Appointment.private_code_digest,
                    Appointment.private_code_ciphertext,
                ).where(Appointment.appointment_id == confirmed.appointment_id)
            ).one()

        retry = PrepareNotificationRetry(
            unit_of_work=PostgresNotificationRetryUnitOfWork(migrated_engine),
            clock=FixedClock(fixture["now"]),  # type: ignore[arg-type]
        ).execute(original_delivery_id)

        with migrated_engine.connect() as connection:
            after = connection.execute(
                select(
                    Appointment.service_snapshot_name,
                    Appointment.scheduled_start,
                    Appointment.status,
                    Appointment.private_code_digest,
                    Appointment.private_code_ciphertext,
                ).where(Appointment.appointment_id == confirmed.appointment_id)
            ).one()
            stored_retry = connection.execute(
                select(
                    NotificationDelivery.appointment_id,
                    NotificationDelivery.event,
                    NotificationDelivery.channel,
                    NotificationDelivery.status,
                    NotificationDelivery.previous_delivery_id,
                    NotificationDelivery.sanitized_error,
                ).where(NotificationDelivery.notification_delivery_id == retry.delivery_id)
            ).one()

        assert retry.recipient == "current-contact@example.test"
        assert retry.previous_delivery_id == original_delivery_id
        assert after == before
        assert tuple(stored_retry) == (
            confirmed.appointment_id,
            "appointment_created",
            "email",
            "pending",
            original_delivery_id,
            None,
        )
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


@pytest.mark.integration
def test_t054_concurrent_same_reference_returns_one_identical_confirmation(
    migrated_engine: Engine,
) -> None:
    fixture = seed_confirmation_fixture(migrated_engine)
    barrier = Barrier(2)

    def confirm(attempt: int):
        barrier.wait(timeout=10)
        return confirmation_service(
            migrated_engine,
            fixture["now"],
            entropy_byte=attempt + 1,
        ).execute(confirmation_command(fixture, f"same-reference-{attempt}"))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                future.result(timeout=20)
                for future in (
                    executor.submit(confirm, 0),
                    executor.submit(confirm, 1),
                )
            )

        with migrated_engine.connect() as connection:
            appointment_count = connection.execute(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            delivery_count = connection.execute(
                select(func.count())
                .select_from(NotificationDelivery)
                .join(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()
            reminder_count = connection.execute(
                select(func.count())
                .select_from(AppointmentReminder)
                .join(Appointment)
                .where(Appointment.service_id == fixture["service_id"])
            ).scalar_one()

        assert results[0].appointment_id == results[1].appointment_id
        assert results[0].private_code == results[1].private_code
        assert results[0].delivery_ids == results[1].delivery_ids
        assert results[0].deliveries == results[1].deliveries
        assert appointment_count == 1
        assert delivery_count == 2
        assert reminder_count == 1
    finally:
        cleanup_confirmation_fixture(migrated_engine, fixture)


def confirmation_service(
    engine: Engine,
    now: datetime,
    entropy_byte: int = 1,
) -> ConfirmAppointment:
    return ConfirmAppointment(
        unit_of_work=PostgresAppointmentConfirmationUnitOfWork(engine),
        clock=FixedClock(now),
        secret_generator=SequenceSecretGenerator(
            [bytes([entropy_byte]) * 16],
        ),
        private_code_protection=TestPrivateCodeProtection(),
    )


def confirmation_with_notifications(
    engine: Engine,
    now: datetime,
    *,
    email: EmailSimulator,
    whatsapp: WhatsAppSimulator,
) -> ConfirmAppointmentWithNotifications:
    return ConfirmAppointmentWithNotifications(
        confirmation=confirmation_service(engine, now),
        dispatcher=NotificationDispatcher(
            email_port=email,
            whatsapp_port=whatsapp,
            result_writer=PostgresNotificationDeliveryResultWriter(engine),
        ),
        clock=FixedClock(now),
    )


def confirmation_command(
    fixture: dict[str, object],
    marker: str,
    reference_index: int = 0,
    *,
    origin: str = PUBLIC_APPOINTMENT_ORIGIN,
    confirmed_by_account_id: int | None = None,
) -> ConfirmAppointmentCommand:
    return ConfirmAppointmentCommand(
        reference_digest=fixture["reference_digests"][reference_index],  # type: ignore[index]
        first_name="Clienta",
        last_name="Sintética",
        phone="5510000000",
        email=f"{marker}@example.test",
        service_id=fixture["service_id"],  # type: ignore[arg-type]
        branch="chiconcuac",
        scheduled_start=fixture["scheduled_start"],  # type: ignore[arg-type]
        privacy_consent=create_privacy_consent_evidence(
            privacy_notice_version_id=fixture["privacy_notice_version_id"],  # type: ignore[arg-type]
            accepted_at=fixture["now"],  # type: ignore[arg-type]
            origin=origin,
            contact_processing_authorized=True,
            adult_responsibility_declared=True,
            confirmed_by_account_id=confirmed_by_account_id,
        ),
    )


def seed_confirmation_fixture(
    engine: Engine,
    *,
    reference_count: int = 1,
    notice: timedelta | None = None,
) -> dict[str, object]:
    marker = uuid4().hex
    if notice is None:
        now = datetime.now(tz=BUSINESS_TIME_ZONE).replace(microsecond=0)
        scheduled_start = unused_future_start(engine)
    else:
        scheduled_start = datetime.combine(
            datetime.now(tz=BUSINESS_TIME_ZONE).date() + timedelta(days=2),
            time(hour=10),
            tzinfo=BUSINESS_TIME_ZONE,
        )
        now = scheduled_start - notice
    reference_digests = tuple(
        hashlib.sha256(f"reference:{marker}:{index}".encode("ascii")).digest()
        for index in range(reference_count)
    )
    with engine.begin() as connection:
        service_id = connection.execute(
            insert(Service)
            .values(
                name=f"Servicio confirmación {marker}",
                description="Synthetic confirmation service",
                duration_minutes=60,
                price=Decimal("350.00"),
                is_active=True,
                available_chiconcuac=True,
                available_texcoco=True,
            )
            .returning(Service.service_id)
        ).scalar_one()
        privacy_notice_version_id = connection.execute(
            insert(PrivacyNoticeVersion)
            .values(
                version=f"synthetic-confirmation-{marker}",
                content="Synthetic privacy notice for transaction testing.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()
        connection.execute(
            insert(BookingConfirmationReference),
            [
                {
                    "reference_digest": digest,
                    "generated_at": now,
                    "expires_at": now + timedelta(hours=24),
                    "consumed_at": None,
                    "appointment_id": None,
                }
                for digest in reference_digests
            ],
        )
    return {
        "service_id": service_id,
        "service_name": f"Servicio confirmación {marker}",
        "privacy_notice_version_id": privacy_notice_version_id,
        "reference_digests": reference_digests,
        "now": now,
        "scheduled_start": scheduled_start,
    }


def cleanup_confirmation_fixture(engine: Engine, fixture: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(Appointment).where(Appointment.service_id == fixture["service_id"])
        )
        connection.execute(
            delete(BookingConfirmationReference).where(
                BookingConfirmationReference.reference_digest.in_(
                    fixture["reference_digests"]
                )
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


def unused_future_start(engine: Engine) -> datetime:
    today = datetime.now(tz=BUSINESS_TIME_ZONE).date()
    for day_offset in range(80, 90):
        candidate = datetime.combine(
            today + timedelta(days=day_offset),
            time(hour=17),
            tzinfo=BUSINESS_TIME_ZONE,
        )
        with engine.connect() as connection:
            occupied = connection.execute(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.status == "scheduled",
                    Appointment.scheduled_start < candidate + timedelta(hours=1),
                    Appointment.scheduled_end > candidate,
                )
            ).scalar_one()
        if occupied == 0:
            return candidate
    raise AssertionError("No unused synthetic appointment slot was found.")
