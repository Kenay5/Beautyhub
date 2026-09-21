"""T086 unit evidence for modification and cancellation message templates."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from backend.app.application.change_notification_templates import (
    prepare_cancellation_notifications,
    prepare_modification_notifications,
)
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


@pytest.mark.parametrize(
    ("prepare", "status", "opening"),
    (
        (prepare_modification_notifications, "scheduled", "Tu cita fue modificada."),
        (prepare_cancellation_notifications, "cancelled", "Tu cita fue cancelada."),
    ),
)
def test_t086_prepares_the_approved_summary_for_both_channels(
    prepare, status: str, opening: str
) -> None:
    email, whatsapp = prepare(appointment=_appointment(status=status))

    assert email.channel == EMAIL_CHANNEL
    assert email.recipient == "clienta@example.test"
    assert whatsapp.channel == WHATSAPP_CHANNEL
    assert whatsapp.recipient == "5510000000"
    assert email.content == whatsapp.content
    for expected_line in (
        opening,
        "Servicio: Servicio sintético",
        "Fecha: 15 de junio de 2030",
        "Horario: 5:30 p. m.",
        "Sucursal: Texcoco",
        "Duración: 1 hora 30 minutos",
        f"Estado: {'Programada' if status == 'scheduled' else 'Cancelada'}",
        "Precio: $450.00 MXN",
    ):
        assert expected_line in email.content


def test_t086_change_templates_never_reveal_code_or_cancellation_reason() -> None:
    appointment = _appointment(status="cancelled")
    notifications = prepare_cancellation_notifications(appointment=appointment)

    for notification in notifications:
        assert "Código privado" not in notification.content
        assert "synthetic-ciphertext" not in notification.content
        assert "Cambio de planes" not in notification.content


def _appointment(*, status: str) -> ScheduledAppointment:
    scheduled_start = datetime(2030, 6, 15, 17, 30, tzinfo=BUSINESS_TIME_ZONE)
    return ScheduledAppointment(
        private_code_ciphertext=b"synthetic-ciphertext",
        private_code_digest=b"synthetic-digest",
        first_name="Clienta",
        last_name="Sintética",
        phone="5510000000",
        email="clienta@example.test",
        service_snapshot=AppointmentServiceSnapshot(
            service_id=13,
            name="Servicio sintético",
            duration_minutes=90,
            price=Decimal("450.00"),
        ),
        branch="texcoco",
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_start,
        status=status,
        privacy_consent=create_privacy_consent_evidence(
            privacy_notice_version_id=7,
            accepted_at=datetime(2030, 6, 1, 12, tzinfo=BUSINESS_TIME_ZONE),
            origin=PUBLIC_APPOINTMENT_ORIGIN,
            contact_processing_authorized=True,
            adult_responsibility_declared=True,
            confirmed_by_account_id=None,
        ),
    )
