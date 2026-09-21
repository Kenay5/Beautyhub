"""T052 unit tests for transactional appointment confirmation decisions."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.confirm_appointment import (
    AppointmentConfirmationReferenceError,
    AppointmentScheduleConflictError,
    ConfirmationDeliveryResult,
    ConfirmAppointment,
    ConfirmAppointmentCommand,
    LockedBookingConfirmationReference,
    StoredConfirmedAppointment,
)
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.application.private_code import PrivateCode
from backend.app.domain.appointment import ScheduledAppointment
from backend.app.domain.privacy_consent import (
    ADMINISTRATIVE_APPOINTMENT_ORIGIN,
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.schedule import ScheduledInterval, TimeInterval
from backend.app.domain.service import AppointmentServiceSelectionError, ServiceDraft
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.domain.appointment_reminder import is_initial_reminder_eligible


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
START = datetime(2030, 6, 2, 11, tzinfo=BUSINESS_TIME_ZONE)


class FakePrivateCodeProtection:
    def __init__(self) -> None:
        self._codes_by_ciphertext: dict[bytes, PrivateCode] = {}

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


class FakeConfirmationRepository:
    def __init__(self) -> None:
        self.reference = LockedBookingConfirmationReference(
            reference_id=17,
            expires_at=NOW + timedelta(hours=24),
            consumed_at=None,
            appointment_id=None,
        )
        self.service = ServiceDraft(
            name="Servicio vigente",
            description=None,
            duration_minutes=60,
            price=Decimal("350.00"),
            is_active=True,
            available_chiconcuac=True,
            available_texcoco=False,
        )
        self.scheduled_intervals: tuple[ScheduledInterval, ...] = ()
        self.blocks: tuple[TimeInterval, ...] = ()
        self.created_appointments: list[ScheduledAppointment] = []
        self.delivery_calls: list[tuple[int, datetime]] = []
        self.created_reminders: list[dict[str, object]] = []
        self.deliveries: tuple[
            ConfirmationDeliveryResult,
            ConfirmationDeliveryResult,
        ] | None = None
        self.consumed_reference: tuple[int, int, datetime] | None = None
        self.schedule_locked = False

    def lock_schedule(self) -> None:
        self.schedule_locked = True

    def lock_confirmation_reference(
        self,
        reference_digest: bytes,
    ) -> LockedBookingConfirmationReference | None:
        assert self.schedule_locked
        return self.reference if reference_digest == b"reference-digest" else None

    def get_service_for_update(self, service_id: int) -> ServiceDraft | None:
        assert self.schedule_locked
        return self.service if service_id == 13 else None

    def list_scheduled_intervals_for_update(self) -> tuple[ScheduledInterval, ...]:
        assert self.schedule_locked
        return self.scheduled_intervals

    def list_applicable_blocks_for_update(
        self,
        branch: str,
    ) -> tuple[TimeInterval, ...]:
        assert branch == "chiconcuac"
        return self.blocks

    def create_appointment(self, appointment: ScheduledAppointment) -> int:
        self.created_appointments.append(appointment)
        return 29

    def create_pending_deliveries(
        self,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> tuple[ConfirmationDeliveryResult, ConfirmationDeliveryResult]:
        self.delivery_calls.append((appointment_id, status_changed_at))
        self.deliveries = (
            ConfirmationDeliveryResult(31, "email", "pending"),
            ConfirmationDeliveryResult(32, "whatsapp", "pending"),
        )
        return self.deliveries

    def create_initial_reminder(
        self,
        *,
        appointment_id: int,
        appointment_scheduled_start: datetime,
        send_at: datetime,
        status_changed_at: datetime,
    ) -> None:
        self.created_reminders.append(
            {
                "appointment_id": appointment_id,
                "appointment_scheduled_start": appointment_scheduled_start,
                "send_at": send_at,
                "status_changed_at": status_changed_at,
            }
        )

    def get_confirmed_appointment(
        self,
        appointment_id: int,
    ) -> StoredConfirmedAppointment | None:
        if (
            appointment_id != 29
            or not self.created_appointments
            or self.deliveries is None
        ):
            return None
        appointment = self.created_appointments[0]
        return StoredConfirmedAppointment(
            appointment_id=29,
            appointment=appointment,
            private_code_ciphertext=appointment.private_code_ciphertext,
            deliveries=self.deliveries,
        )

    def consume_confirmation_reference(
        self,
        reference_id: int,
        appointment_id: int,
        consumed_at: datetime,
    ) -> bool:
        self.consumed_reference = (reference_id, appointment_id, consumed_at)
        self.reference = LockedBookingConfirmationReference(
            reference_id=reference_id,
            expires_at=self.reference.expires_at,
            consumed_at=consumed_at,
            appointment_id=appointment_id,
        )
        return True


class FakeConfirmationUnitOfWork:
    def __init__(self, repository: FakeConfirmationRepository) -> None:
        self.repository = repository

    @contextmanager
    def transaction(self) -> Iterator[FakeConfirmationRepository]:
        yield self.repository


def confirmation_command(**overrides: object) -> ConfirmAppointmentCommand:
    values = {
        "reference_digest": b"reference-digest",
        "first_name": "  Clienta ",
        "last_name": " Ejemplo ",
        "phone": "55 1000 0000",
        "email": " clienta@example.test ",
        "service_id": 13,
        "branch": "chiconcuac",
        "scheduled_start": START,
        "privacy_consent": create_privacy_consent_evidence(
            privacy_notice_version_id=7,
            accepted_at=NOW,
            origin=PUBLIC_APPOINTMENT_ORIGIN,
            contact_processing_authorized=True,
            adult_responsibility_declared=True,
            confirmed_by_account_id=None,
        ),
        **overrides,
    }
    return ConfirmAppointmentCommand(**values)  # type: ignore[arg-type]


def confirmer(
    repository: FakeConfirmationRepository,
    protection: FakePrivateCodeProtection | None = None,
) -> ConfirmAppointment:
    return ConfirmAppointment(
        unit_of_work=FakeConfirmationUnitOfWork(repository),
        clock=FixedClock(NOW),
        secret_generator=SequenceSecretGenerator([b"\x01" * 16]),
        private_code_protection=protection or FakePrivateCodeProtection(),
    )


def test_t052_confirms_appointment_and_two_delivery_intents_together() -> None:
    repository = FakeConfirmationRepository()

    result = confirmer(repository).execute(confirmation_command())

    assert result.appointment_id == 29
    assert result.delivery_ids == (31, 32)
    assert len(repository.created_appointments) == 1
    assert repository.created_appointments[0].service_snapshot.name == "Servicio vigente"
    assert repository.delivery_calls == [(29, NOW)]
    assert repository.consumed_reference == (17, 29, NOW)


@pytest.mark.parametrize(
    ("origin", "confirmed_by_account_id", "notice", "should_schedule"),
    (
        pytest.param(
            PUBLIC_APPOINTMENT_ORIGIN,
            None,
            timedelta(hours=24, minutes=15),
            True,
            id="public-more-than-24-hours",
        ),
        pytest.param(
            ADMINISTRATIVE_APPOINTMENT_ORIGIN,
            41,
            timedelta(hours=25),
            True,
            id="administrative-more-than-24-hours",
        ),
        pytest.param(
            PUBLIC_APPOINTMENT_ORIGIN,
            None,
            timedelta(hours=24),
            False,
            id="public-exactly-24-hours",
        ),
        pytest.param(
            ADMINISTRATIVE_APPOINTMENT_ORIGIN,
            41,
            timedelta(hours=23, minutes=45),
            False,
            id="administrative-less-than-24-hours",
        ),
    ),
)
def test_t093b_schedules_only_an_initial_reminder_strictly_more_than_24_hours_ahead(
    origin: str,
    confirmed_by_account_id: int | None,
    notice: timedelta,
    should_schedule: bool,
) -> None:
    repository = FakeConfirmationRepository()
    scheduled_start = NOW + notice
    consent = create_privacy_consent_evidence(
        privacy_notice_version_id=7,
        accepted_at=NOW,
        origin=origin,
        contact_processing_authorized=True,
        adult_responsibility_declared=True,
        confirmed_by_account_id=confirmed_by_account_id,
    )

    confirmer(repository).execute(
        confirmation_command(
            scheduled_start=scheduled_start,
            privacy_consent=consent,
        )
    )

    if not should_schedule:
        assert repository.created_reminders == []
        return

    assert repository.created_reminders == [
        {
            "appointment_id": 29,
            "appointment_scheduled_start": scheduled_start,
            "send_at": scheduled_start - timedelta(hours=24),
            "status_changed_at": NOW,
        }
    ]


@pytest.mark.parametrize(
    ("notice", "expected"),
    (
        pytest.param(timedelta(hours=24, microseconds=1), True, id="just-over"),
        pytest.param(timedelta(hours=24), False, id="exactly-24-hours"),
        pytest.param(timedelta(hours=23, minutes=59, seconds=59), False, id="just-under"),
    ),
)
def test_t093b_initial_reminder_eligibility_uses_an_exact_absolute_24_hour_boundary(
    notice: timedelta,
    expected: bool,
) -> None:
    assert (
        is_initial_reminder_eligible(
            scheduled_start=NOW + notice,
            current_time=NOW,
        )
        is expected
    )


def test_t053_retry_returns_original_result_without_new_writes() -> None:
    repository = FakeConfirmationRepository()
    protection = FakePrivateCodeProtection()
    service = confirmer(repository, protection)
    original = service.execute(confirmation_command())

    retry = service.execute(
        confirmation_command(
            service_id=999,
            scheduled_start=NOW - timedelta(days=1),
        )
    )

    assert retry == original
    assert retry.private_code.value == "AQEBAQEBAQEBAQEBAQEBAQ"
    assert len(repository.created_appointments) == 1
    assert repository.delivery_calls == [(29, NOW)]
    assert repository.consumed_reference == (17, 29, NOW)


@pytest.mark.parametrize("conflict_kind", ["appointment", "block"])
def test_t052_rejects_current_schedule_conflicts_before_writing(
    conflict_kind: str,
) -> None:
    repository = FakeConfirmationRepository()
    occupied = TimeInterval(START, START + timedelta(hours=1))
    if conflict_kind == "appointment":
        repository.scheduled_intervals = (
            ScheduledInterval(occupied, "texcoco"),
        )
    else:
        repository.blocks = (occupied,)

    with pytest.raises(AppointmentScheduleConflictError):
        confirmer(repository).execute(confirmation_command())

    assert repository.created_appointments == []
    assert repository.delivery_calls == []
    assert repository.consumed_reference is None


def test_t052_rejects_a_reference_at_its_exact_expiration() -> None:
    repository = FakeConfirmationRepository()
    repository.reference = LockedBookingConfirmationReference(
        reference_id=17,
        expires_at=NOW,
        consumed_at=None,
        appointment_id=None,
    )

    with pytest.raises(AppointmentConfirmationReferenceError):
        confirmer(repository).execute(confirmation_command())

    assert repository.created_appointments == []
    assert repository.delivery_calls == []


def test_t052_revalidates_the_current_service_state_under_the_guard() -> None:
    repository = FakeConfirmationRepository()
    repository.service = ServiceDraft(
        name="Servicio desactivado",
        description=None,
        duration_minutes=60,
        price=Decimal("350.00"),
        is_active=False,
        available_chiconcuac=True,
        available_texcoco=False,
    )

    with pytest.raises(AppointmentServiceSelectionError, match="must be active"):
        confirmer(repository).execute(confirmation_command())

    assert repository.created_appointments == []
    assert repository.delivery_calls == []
