"""Prepared reminder messages without private-code or recovery data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

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


@dataclass(frozen=True)
class ReminderNotificationData:
    """Current appointment data approved for one reminder."""

    email: str = field(repr=False)
    phone: str = field(repr=False)
    service_name: str
    duration_minutes: int
    price: Decimal
    branch: str
    scheduled_start: datetime


def prepare_reminder_notifications(
    *,
    appointment: ScheduledAppointment,
) -> tuple[OutboundNotification, OutboundNotification]:
    """Prepare the approved six-field reminder for the current contacts."""

    snapshot = appointment.service_snapshot
    return prepare_reminder_notifications_from_data(
        data=ReminderNotificationData(
            email=appointment.email,
            phone=appointment.phone,
            service_name=snapshot.name,
            duration_minutes=snapshot.duration_minutes,
            price=snapshot.price,
            branch=appointment.branch,
            scheduled_start=appointment.scheduled_start,
        )
    )


def prepare_reminder_notifications_from_data(
    *,
    data: ReminderNotificationData,
) -> tuple[OutboundNotification, OutboundNotification]:
    """Prepare both reminder channels from transactionally reloaded data."""

    content = _reminder_content(data)
    return (
        OutboundNotification(
            channel=EMAIL_CHANNEL,
            recipient=data.email,
            content=content,
        ),
        OutboundNotification(
            channel=WHATSAPP_CHANNEL,
            recipient=data.phone,
            content=content,
        ),
    )


def _reminder_content(data: ReminderNotificationData) -> str:
    scheduled_start = to_business_time(data.scheduled_start)
    return "\n".join(
        (
            "Recordatorio de tu cita.",
            f"Servicio: {data.service_name}",
            f"Fecha: {_format_date(scheduled_start)}",
            f"Horario: {_format_time(scheduled_start)}",
            f"Sucursal: {_format_branch(data.branch)}",
            f"Duración: {_format_duration(data.duration_minutes)}",
            f"Precio: ${data.price:.2f} MXN",
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
