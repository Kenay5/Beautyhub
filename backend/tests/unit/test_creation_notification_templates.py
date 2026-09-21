"""T085 unit evidence for transactional creation message templates."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from backend.app.application.creation_notification_templates import (
    prepare_creation_notifications,
)
from backend.app.application.private_code import PrivateCode
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
)
from backend.app.domain.appointment import (
    AppointmentServiceSnapshot,
    ScheduledAppointment,
)
from backend.app.domain.privacy_consent import (
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


def test_t085_prepares_the_approved_creation_summary_for_email_and_whatsapp() -> None:
    notifications = prepare_creation_notifications(
        appointment=_appointment(),
        private_code=PrivateCode("synthetic-private-code-not-for-production"),
    )

    email, whatsapp = notifications
    assert email.channel == EMAIL_CHANNEL
    assert email.recipient == "clienta@example.test"
    assert whatsapp.channel == WHATSAPP_CHANNEL
    assert whatsapp.recipient == "5510000000"
    assert email.content == whatsapp.content
    for expected_line in (
        "Servicio: Servicio sintético",
        "Fecha: 15 de junio de 2030",
        "Horario: 5:30 p. m.",
        "Sucursal: Texcoco",
        "Duración: 1 hora 30 minutos",
        "Estado: Programada",
        "Precio: $450.00 MXN",
        "Código privado: synthetic-private-code-not-for-production",
    ):
        assert expected_line in email.content


def test_t085_template_and_notification_debug_output_hide_contacts_and_private_code() -> None:
    private_code = PrivateCode("synthetic-private-code-not-for-production")
    email, whatsapp = prepare_creation_notifications(
        appointment=_appointment(),
        private_code=private_code,
    )

    for value in (
        "clienta@example.test",
        "5510000000",
        private_code.value,
    ):
        assert value not in repr(email)
        assert value not in repr(whatsapp)


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
