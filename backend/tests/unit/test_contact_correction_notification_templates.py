"""T086A unit evidence for private-code resends after contact correction."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from backend.app.application.change_notification_templates import (
    prepare_modification_notifications,
)
from backend.app.application.contact_correction_notification_templates import (
    ContactCorrectionNotificationError,
    prepare_contact_correction_notifications,
)
from backend.app.application.private_code import PrivateCode
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
)
from backend.app.domain.appointment import AppointmentServiceSnapshot, ScheduledAppointment
from backend.app.domain.privacy_consent import (
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


PRIVATE_CODE = PrivateCode("synthetic-private-code-not-for-production")


@pytest.mark.parametrize(
    ("email_changed", "phone_changed", "expected_channels", "expected_recipients"),
    (
        (True, False, (EMAIL_CHANNEL,), ("updated@example.test",)),
        (False, True, (WHATSAPP_CHANNEL,), ("5520000000",)),
        (
            True,
            True,
            (EMAIL_CHANNEL, WHATSAPP_CHANNEL),
            ("updated@example.test", "5520000000"),
        ),
    ),
)
def test_t086a_resends_the_same_code_only_to_corrected_contacts(
    email_changed: bool,
    phone_changed: bool,
    expected_channels: tuple[str, ...],
    expected_recipients: tuple[str, ...],
) -> None:
    notifications = prepare_contact_correction_notifications(
        appointment=_appointment(),
        private_code=PRIVATE_CODE,
        email_changed=email_changed,
        phone_changed=phone_changed,
    )

    assert tuple(notification.channel for notification in notifications) == expected_channels
    assert tuple(notification.recipient for notification in notifications) == expected_recipients
    for notification in notifications:
        for expected_line in (
            "Actualizamos tus datos de contacto.",
            "Servicio: Servicio sintético",
            "Fecha: 15 de junio de 2030",
            "Horario: 5:30 p. m.",
            "Sucursal: Texcoco",
            "Duración: 1 hora 30 minutos",
            "Estado: Programada",
            "Precio: $450.00 MXN",
            f"Código privado: {PRIVATE_CODE.value}",
        ):
            assert expected_line in notification.content
        assert PRIVATE_CODE.value not in repr(notification)


def test_t086a_does_not_add_the_code_to_the_ordinary_modification_message() -> None:
    appointment = _appointment()
    correction = prepare_contact_correction_notifications(
        appointment=appointment,
        private_code=PRIVATE_CODE,
        email_changed=True,
        phone_changed=False,
    )
    ordinary_email, ordinary_whatsapp = prepare_modification_notifications(
        appointment=appointment
    )

    assert PRIVATE_CODE.value in correction[0].content
    assert PRIVATE_CODE.value not in ordinary_email.content
    assert PRIVATE_CODE.value not in ordinary_whatsapp.content


@pytest.mark.parametrize(
    ("email_changed", "phone_changed"),
    ((False, False), ("true", False), (False, 1)),
)
def test_t086a_rejects_missing_or_invalid_contact_change_flags(
    email_changed: object, phone_changed: object
) -> None:
    with pytest.raises(ContactCorrectionNotificationError):
        prepare_contact_correction_notifications(
            appointment=_appointment(),
            private_code=PRIVATE_CODE,
            email_changed=email_changed,  # type: ignore[arg-type]
            phone_changed=phone_changed,  # type: ignore[arg-type]
        )


def _appointment() -> ScheduledAppointment:
    scheduled_start = datetime(2030, 6, 15, 17, 30, tzinfo=BUSINESS_TIME_ZONE)
    return ScheduledAppointment(
        private_code_ciphertext=b"synthetic-ciphertext",
        private_code_digest=b"synthetic-digest",
        first_name="Clienta",
        last_name="Sintética",
        phone="5520000000",
        email="updated@example.test",
        service_snapshot=AppointmentServiceSnapshot(
            service_id=13,
            name="Servicio sintético",
            duration_minutes=90,
            price=Decimal("450.00"),
        ),
        branch="texcoco",
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_start,
        status="scheduled",
        privacy_consent=create_privacy_consent_evidence(
            privacy_notice_version_id=7,
            accepted_at=datetime(2030, 6, 1, 12, tzinfo=BUSINESS_TIME_ZONE),
            origin=PUBLIC_APPOINTMENT_ORIGIN,
            contact_processing_authorized=True,
            adult_responsibility_declared=True,
            confirmed_by_account_id=None,
        ),
    )
