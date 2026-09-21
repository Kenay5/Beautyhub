"""Prepared private-code resend messages for corrected appointment contacts."""

from __future__ import annotations

from datetime import datetime

from backend.app.application.private_code import PrivateCode
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    OutboundNotification,
)
from backend.app.domain.appointment import ScheduledAppointment
from backend.app.domain.time import to_business_time


_MONTH_NAMES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


class ContactCorrectionNotificationError(ValueError):
    """Raised when a private-code resend has no corrected recipient."""


def prepare_contact_correction_notifications(
    *,
    appointment: ScheduledAppointment,
    private_code: PrivateCode,
    email_changed: bool,
    phone_changed: bool,
) -> tuple[OutboundNotification, ...]:
    """Prepare private-code resends only for the updated appointment contacts."""

    _require_contact_change(email_changed=email_changed, phone_changed=phone_changed)
    content = _contact_correction_content(appointment, private_code)
    notifications: list[OutboundNotification] = []
    if email_changed:
        notifications.append(
            OutboundNotification(
                channel=EMAIL_CHANNEL,
                recipient=appointment.email,
                content=content,
            )
        )
    if phone_changed:
        notifications.append(
            OutboundNotification(
                channel=WHATSAPP_CHANNEL,
                recipient=appointment.phone,
                content=content,
            )
        )
    return tuple(notifications)


def _require_contact_change(*, email_changed: bool, phone_changed: bool) -> None:
    if not isinstance(email_changed, bool) or not isinstance(phone_changed, bool):
        raise ContactCorrectionNotificationError("contact changes must be boolean values.")
    if not email_changed and not phone_changed:
        raise ContactCorrectionNotificationError("at least one contact must be corrected.")


def _contact_correction_content(
    appointment: ScheduledAppointment, private_code: PrivateCode
) -> str:
    scheduled_start = to_business_time(appointment.scheduled_start)
    snapshot = appointment.service_snapshot
    return "\n".join(
        (
            "Actualizamos tus datos de contacto.",
            "Conserva este código privado para gestionar tu cita.",
            f"Servicio: {snapshot.name}",
            f"Fecha: {_format_date(scheduled_start)}",
            f"Horario: {_format_time(scheduled_start)}",
            f"Sucursal: {_format_branch(appointment.branch)}",
            f"Duración: {_format_duration(snapshot.duration_minutes)}",
            f"Estado: {_format_status(appointment.status)}",
            f"Precio: ${snapshot.price:.2f} MXN",
            f"Código privado: {private_code.value}",
        )
    )


def _format_date(scheduled_start: datetime) -> str:
    return (
        f"{scheduled_start.day} de {_MONTH_NAMES[scheduled_start.month - 1]} "
        f"de {scheduled_start.year}"
    )


def _format_time(scheduled_start: datetime) -> str:
    hour = scheduled_start.hour % 12 or 12
    period = "a. m." if scheduled_start.hour < 12 else "p. m."
    return f"{hour}:{scheduled_start.minute:02d} {period}"


def _format_duration(minutes: int) -> str:
    hours, remaining_minutes = divmod(minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append("1 hora" if hours == 1 else f"{hours} horas")
    if remaining_minutes:
        parts.append(f"{remaining_minutes} minutos")
    return " ".join(parts) or "0 minutos"


def _format_branch(branch: str) -> str:
    return {"chiconcuac": "Chiconcuac", "texcoco": "Texcoco"}.get(branch, branch)


def _format_status(status: str) -> str:
    return {
        "scheduled": "Programada",
        "cancelled": "Cancelada",
        "completed": "Completada",
        "no_show": "No asistió",
        "unrecorded_result": "Resultado no registrado",
    }.get(status, status)
