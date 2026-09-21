"""T051 unit tests for the scheduled appointment aggregate."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.app.domain.appointment import (
    SCHEDULED_APPOINTMENT_STATUS,
    AppointmentValidationError,
    create_scheduled_appointment,
)
from backend.app.domain.privacy_consent import (
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.service import (
    AppointmentServiceSelectionError,
    ServiceDraft,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE, InstantValidationError


def appointment_service(**overrides: object) -> ServiceDraft:
    values = {
        "name": "Manicure de prueba",
        "description": None,
        "duration_minutes": 60,
        "price": Decimal("350.00"),
        "is_active": True,
        "available_chiconcuac": True,
        "available_texcoco": False,
        **overrides,
    }
    return ServiceDraft(**values)  # type: ignore[arg-type]


def consent_evidence():
    return create_privacy_consent_evidence(
        privacy_notice_version_id=7,
        accepted_at=datetime(2030, 6, 1, 12, tzinfo=BUSINESS_TIME_ZONE),
        origin=PUBLIC_APPOINTMENT_ORIGIN,
        contact_processing_authorized=True,
        adult_responsibility_declared=True,
        confirmed_by_account_id=None,
    )


def create_valid_appointment(**overrides: object):
    values = {
        "private_code_ciphertext": b"protected-code",
        "private_code_digest": b"lookup-digest",
        "first_name": "  Ana  María ",
        "last_name": "  O'Connor-López ",
        "phone": "+52 (55) 1000-0000",
        "email": "  ana@example.test ",
        "service_id": 13,
        "service": appointment_service(),
        "branch": "chiconcuac",
        "scheduled_start": datetime(2030, 6, 15, 17, tzinfo=BUSINESS_TIME_ZONE),
        "privacy_consent": consent_evidence(),
        **overrides,
    }
    return create_scheduled_appointment(**values)


def test_t051_preserves_contact_branch_schedule_and_current_service_terms() -> None:
    appointment = create_valid_appointment()

    assert appointment.private_code_ciphertext == b"protected-code"
    assert appointment.private_code_digest == b"lookup-digest"
    assert appointment.first_name == "Ana  María"
    assert appointment.last_name == "O'Connor-López"
    assert appointment.phone == "5510000000"
    assert appointment.email == "ana@example.test"
    assert appointment.branch == "chiconcuac"
    assert appointment.scheduled_start == datetime(
        2030, 6, 15, 17, tzinfo=BUSINESS_TIME_ZONE
    )
    assert appointment.scheduled_end == datetime(
        2030, 6, 15, 18, tzinfo=BUSINESS_TIME_ZONE
    )
    assert appointment.status == SCHEDULED_APPOINTMENT_STATUS
    assert appointment.service_snapshot.service_id == 13
    assert appointment.service_snapshot.name == "Manicure de prueba"
    assert appointment.service_snapshot.duration_minutes == 60
    assert appointment.service_snapshot.price == Decimal("350.00")
    assert appointment.privacy_consent == consent_evidence()


def test_t051_keeps_service_snapshot_after_the_current_service_changes() -> None:
    appointment = create_valid_appointment()
    changed_service = appointment_service(
        name="Manicure actualizado",
        duration_minutes=90,
        price=Decimal("500.00"),
    )

    assert appointment.service_snapshot.name != changed_service.name
    assert appointment.service_snapshot.duration_minutes != changed_service.duration_minutes
    assert appointment.service_snapshot.price != changed_service.price


def test_t051_rejects_a_service_inactive_or_unavailable_in_the_selected_branch() -> None:
    with pytest.raises(AppointmentServiceSelectionError, match="must be active"):
        create_valid_appointment(service=appointment_service(is_active=False))

    with pytest.raises(AppointmentServiceSelectionError, match="not available"):
        create_valid_appointment(
            branch="texcoco",
            service=appointment_service(available_texcoco=False),
        )


@pytest.mark.parametrize("service_id", [0, -1, True, "13"])
def test_t051_requires_a_positive_persistable_service_identifier(service_id: object) -> None:
    with pytest.raises(AppointmentValidationError, match="service identifier"):
        create_valid_appointment(service_id=service_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("private_code_ciphertext", b""),
        ("private_code_ciphertext", "not-bytes"),
        ("private_code_digest", b""),
        ("private_code_digest", "not-bytes"),
    ],
)
def test_t051_requires_only_protected_private_code_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(AppointmentValidationError, match="private code"):
        create_valid_appointment(**{field: value})


def test_t051_requires_an_aware_scheduled_start() -> None:
    with pytest.raises(InstantValidationError, match="time zone"):
        create_valid_appointment(scheduled_start=datetime(2030, 6, 15, 17))


def test_t051_normalizes_the_schedule_to_the_official_business_time_zone() -> None:
    appointment = create_valid_appointment(
        scheduled_start=datetime(2030, 6, 15, 23, tzinfo=timezone.utc),
    )

    assert appointment.scheduled_start == datetime(
        2030, 6, 15, 17, tzinfo=BUSINESS_TIME_ZONE
    )
    assert appointment.scheduled_end == datetime(
        2030, 6, 15, 18, tzinfo=BUSINESS_TIME_ZONE
    )
