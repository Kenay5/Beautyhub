"""Prepared transactional creation notifications without provider side effects."""

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


def prepare_creation_notifications(
    *,
    appointment: ScheduledAppointment,
    private_code: PrivateCode,
) -> tuple[OutboundNotification, OutboundNotification]:
    """Prepare the approved creation summary for email and WhatsApp only."""

    content = _creation_content(appointment, private_code)
    return (
        OutboundNotification(
            channel=EMAIL_CHANNEL,
            recipient=appointment.email,
            content=content,
        ),
        OutboundNotification(
            channel=WHATSAPP_CHANNEL,
            recipient=appointment.phone,
            content=content,
        ),
    )


def _creation_content(
    appointment: ScheduledAppointment,
    private_code: PrivateCode,
) -> str:
    scheduled_start = to_business_time(appointment.scheduled_start)
    snapshot = appointment.service_snapshot
    return "\n".join(
        (
            "Tu cita quedó programada.",
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
