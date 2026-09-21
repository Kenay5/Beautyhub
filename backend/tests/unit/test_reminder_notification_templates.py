"""T093D unit evidence for safe reminder message templates."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from backend.app.application.reminder_notification_templates import (
    prepare_reminder_notifications,
)
from backend.app.domain.appointment import AppointmentServiceSnapshot, ScheduledAppointment
from backend.app.domain.privacy_consent import (
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


def test_t093d_prepares_the_same_current_contact_safe_summary_for_both_channels() -> None:
    email, whatsapp = prepare_reminder_notifications(appointment=_appointment())

    assert email.channel == "email"
    assert email.recipient == "clienta@example.test"
    assert whatsapp.channel == "whatsapp"
    assert whatsapp.recipient == "5510000000"
    assert email.content == whatsapp.content
    for expected_line in (
        "Servicio: Servicio sintético",
        "Fecha: 15 de junio de 2030",
        "Horario: 5:30 p. m.",
        "Sucursal: Texcoco",
        "Duración: 1 hora 30 minutos",
        "Precio: $450.00 MXN",
    ):
        assert expected_line in email.content


def test_t093d_reminder_content_has_no_private_code_or_recovery_information() -> None:
    appointment = _appointment()
    notifications = prepare_reminder_notifications(appointment=appointment)

    for notification in notifications:
        assert "Código privado" not in notification.content
        assert "synthetic-private-code-not-for-production" not in notification.content
        assert "synthetic-ciphertext" not in notification.content
        assert "synthetic-digest" not in notification.content
        assert "http://" not in notification.content
        assert "https://" not in notification.content
        assert "Estado:" not in notification.content


def _appointment() -> ScheduledAppointment:
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
