"""PostgreSQL transaction adapter for appointment confirmation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import Connection

from backend.app.application.confirm_appointment import (
    APPOINTMENT_CREATED_EVENT,
    EMAIL_CHANNEL,
    PENDING_DELIVERY_STATUS,
    WHATSAPP_CHANNEL,
    AppointmentConfirmationRepository,
    ConfirmationDeliveryResult,
    LockedBookingConfirmationReference,
    StoredConfirmedAppointment,
)
from backend.app.domain.appointment import (
    AppointmentServiceSnapshot,
    ScheduledAppointment,
)
from backend.app.domain.appointment_reminder import SCHEDULED_REMINDER_STATUS
from backend.app.domain.privacy_consent import PrivacyConsentEvidence
from backend.app.domain.schedule import ScheduledInterval, TimeInterval
from backend.app.domain.service import ServiceDraft
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    BookingConfirmationReference,
    NotificationDelivery,
    Service,
)
from backend.app.infrastructure.persistence.schedule_repository import (
    PostgresScheduleRepository,
)


class PostgresAppointmentConfirmationRepository:
    """Persist one confirmation through a caller-owned connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._schedule_repository = PostgresScheduleRepository(connection)

    def lock_schedule(self) -> None:
        self._schedule_repository.lock_schedule()

    def lock_confirmation_reference(
        self,
        reference_digest: bytes,
    ) -> LockedBookingConfirmationReference | None:
        row = self._connection.execute(
            select(
                BookingConfirmationReference.booking_confirmation_reference_id,
                BookingConfirmationReference.expires_at,
                BookingConfirmationReference.consumed_at,
                BookingConfirmationReference.appointment_id,
            )
            .where(BookingConfirmationReference.reference_digest == reference_digest)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        return LockedBookingConfirmationReference(
            reference_id=row.booking_confirmation_reference_id,
            expires_at=row.expires_at,
            consumed_at=row.consumed_at,
            appointment_id=row.appointment_id,
        )

    def get_service_for_update(self, service_id: int) -> ServiceDraft | None:
        row = self._connection.execute(
            select(
                Service.name,
                Service.description,
                Service.duration_minutes,
                Service.price,
                Service.is_active,
                Service.available_chiconcuac,
                Service.available_texcoco,
            )
            .where(Service.service_id == service_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        return ServiceDraft(
            name=row.name,
            description=row.description,
            duration_minutes=row.duration_minutes,
            price=row.price,
            is_active=row.is_active,
            available_chiconcuac=row.available_chiconcuac,
            available_texcoco=row.available_texcoco,
        )

    def list_scheduled_intervals_for_update(self) -> tuple[ScheduledInterval, ...]:
        return self._schedule_repository.list_scheduled_intervals(lock=True)

    def list_applicable_blocks_for_update(
        self,
        branch: str,
    ) -> tuple[TimeInterval, ...]:
        return self._schedule_repository.list_applicable_blocks(branch, lock=True)

    def create_appointment(self, appointment: ScheduledAppointment) -> int:
        consent = appointment.privacy_consent
        return self._connection.execute(
            insert(Appointment)
            .values(
                private_code_ciphertext=appointment.private_code_ciphertext,
                private_code_digest=appointment.private_code_digest,
                first_name=appointment.first_name,
                last_name=appointment.last_name,
                phone=appointment.phone,
                email=appointment.email,
                service_id=appointment.service_snapshot.service_id,
                service_snapshot_name=appointment.service_snapshot.name,
                service_snapshot_duration_minutes=(
                    appointment.service_snapshot.duration_minutes
                ),
                service_snapshot_price=appointment.service_snapshot.price,
                branch=appointment.branch,
                scheduled_start=appointment.scheduled_start,
                scheduled_end=appointment.scheduled_end,
                status=appointment.status,
                cancellation_reason=None,
                origin=consent.origin,
                created_by_account_id=consent.confirmed_by_account_id,
                privacy_notice_version_id=consent.privacy_notice_version_id,
                privacy_notice_accepted_at=consent.accepted_at,
                contact_processing_authorized=(
                    consent.contact_processing_authorized
                ),
                adult_responsibility_declared=(
                    consent.adult_responsibility_declared
                ),
            )
            .returning(Appointment.appointment_id)
        ).scalar_one()

    def create_pending_deliveries(
        self,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> tuple[ConfirmationDeliveryResult, ConfirmationDeliveryResult]:
        rows = self._connection.execute(
            insert(NotificationDelivery)
            .values(
                [
                    _pending_delivery_values(
                        appointment_id,
                        EMAIL_CHANNEL,
                        status_changed_at,
                    ),
                    _pending_delivery_values(
                        appointment_id,
                        WHATSAPP_CHANNEL,
                        status_changed_at,
                    ),
                ]
            )
            .returning(
                NotificationDelivery.notification_delivery_id,
                NotificationDelivery.channel,
                NotificationDelivery.status,
            )
        ).all()
        deliveries = tuple(
            ConfirmationDeliveryResult(
                delivery_id=row.notification_delivery_id,
                channel=row.channel,
                status=row.status,
            )
            for row in rows
        )
        if len(deliveries) != 2:
            raise RuntimeError("appointment confirmation requires two deliveries.")
        return deliveries  # type: ignore[return-value]

    def create_initial_reminder(
        self,
        *,
        appointment_id: int,
        appointment_scheduled_start: datetime,
        send_at: datetime,
        status_changed_at: datetime,
    ) -> None:
        self._connection.execute(
            insert(AppointmentReminder).values(
                appointment_id=appointment_id,
                appointment_scheduled_start=appointment_scheduled_start,
                send_at=send_at,
                status=SCHEDULED_REMINDER_STATUS,
                status_changed_at=status_changed_at,
                claimed_at=None,
                claim_expires_at=None,
            )
        )

    def get_confirmed_appointment(
        self,
        appointment_id: int,
    ) -> StoredConfirmedAppointment | None:
        row = self._connection.execute(
            select(Appointment.__table__).where(
                Appointment.appointment_id == appointment_id
            )
        ).mappings().one_or_none()
        if row is None:
            return None

        delivery_rows = self._connection.execute(
            select(
                NotificationDelivery.notification_delivery_id,
                NotificationDelivery.channel,
                NotificationDelivery.status,
            )
            .where(
                NotificationDelivery.appointment_id == appointment_id,
                NotificationDelivery.event == APPOINTMENT_CREATED_EVENT,
                NotificationDelivery.previous_delivery_id.is_(None),
            )
            .order_by(NotificationDelivery.channel)
        ).all()
        deliveries = tuple(
            ConfirmationDeliveryResult(
                delivery_id=delivery.notification_delivery_id,
                channel=delivery.channel,
                status=delivery.status,
            )
            for delivery in delivery_rows
        )
        if len(deliveries) != 2:
            return None

        consent = PrivacyConsentEvidence(
            privacy_notice_version_id=row["privacy_notice_version_id"],
            accepted_at=row["privacy_notice_accepted_at"],
            origin=row["origin"],
            contact_processing_authorized=row["contact_processing_authorized"],
            adult_responsibility_declared=row["adult_responsibility_declared"],
            confirmed_by_account_id=row["created_by_account_id"],
        )
        appointment = ScheduledAppointment(
            private_code_ciphertext=row["private_code_ciphertext"],
            private_code_digest=row["private_code_digest"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            phone=row["phone"],
            email=row["email"],
            service_snapshot=AppointmentServiceSnapshot(
                service_id=row["service_id"],
                name=row["service_snapshot_name"],
                duration_minutes=row["service_snapshot_duration_minutes"],
                price=row["service_snapshot_price"],
            ),
            branch=row["branch"],
            scheduled_start=row["scheduled_start"],
            scheduled_end=row["scheduled_end"],
            status=row["status"],
            privacy_consent=consent,
        )
        return StoredConfirmedAppointment(
            appointment_id=appointment_id,
            appointment=appointment,
            private_code_ciphertext=row["private_code_ciphertext"],
            deliveries=deliveries,  # type: ignore[arg-type]
        )

    def consume_confirmation_reference(
        self,
        reference_id: int,
        appointment_id: int,
        consumed_at: datetime,
    ) -> bool:
        result = self._connection.execute(
            update(BookingConfirmationReference)
            .where(
                BookingConfirmationReference.booking_confirmation_reference_id
                == reference_id,
                BookingConfirmationReference.consumed_at.is_(None),
                BookingConfirmationReference.appointment_id.is_(None),
                BookingConfirmationReference.expires_at > consumed_at,
            )
            .values(
                consumed_at=consumed_at,
                appointment_id=appointment_id,
            )
        )
        return result.rowcount == 1


class PostgresAppointmentConfirmationUnitOfWork:
    """Own the atomic PostgreSQL transaction for one confirmation."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[AppointmentConfirmationRepository]:
        with self._engine.begin() as connection:
            yield PostgresAppointmentConfirmationRepository(connection)


def _pending_delivery_values(
    appointment_id: int,
    channel: str,
    status_changed_at: datetime,
) -> dict[str, object]:
    return {
        "appointment_id": appointment_id,
        "event": APPOINTMENT_CREATED_EVENT,
        "channel": channel,
        "status": PENDING_DELIVERY_STATUS,
        "status_changed_at": status_changed_at,
        "external_reference": None,
        "appointment_reminder_id": None,
        "previous_delivery_id": None,
        "sanitized_error": None,
    }
