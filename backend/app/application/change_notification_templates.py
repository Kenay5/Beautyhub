"""Prepared modification and cancellation notifications without provider side effects."""

from __future__ import annotations

from datetime import datetime

from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    OutboundNotification,
)
from backend.app.application.change_notification_data import (
    AppointmentChangeNotificationData,
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


def prepare_modification_notifications(
    *, appointment: ScheduledAppointment
) -> tuple[OutboundNotification, OutboundNotification]:
    """Prepare the ordinary summary sent after a confirmed modification."""

    return prepare_modification_notifications_from_data(
        data=_from_appointment(appointment)
    )


def prepare_cancellation_notifications(
    *, appointment: ScheduledAppointment
) -> tuple[OutboundNotification, OutboundNotification]:
    """Prepare the ordinary summary sent after a confirmed cancellation."""

    return prepare_cancellation_notifications_from_data(
        data=_from_appointment(appointment)
    )


def prepare_modification_notifications_from_data(
    *, data: AppointmentChangeNotificationData
) -> tuple[OutboundNotification, OutboundNotification]:
    """Prepare an ordinary modification message from committed safe data."""

    return _prepare_notifications(data=data, opening="Tu cita fue modificada.")


def prepare_cancellation_notifications_from_data(
    *, data: AppointmentChangeNotificationData
) -> tuple[OutboundNotification, OutboundNotification]:
    """Prepare an ordinary cancellation message from committed safe data."""

    return _prepare_notifications(data=data, opening="Tu cita fue cancelada.")


def _prepare_notifications(
    *, data: AppointmentChangeNotificationData, opening: str
) -> tuple[OutboundNotification, OutboundNotification]:
    content = _change_content(data, opening)
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


def _change_content(data: AppointmentChangeNotificationData, opening: str) -> str:
    scheduled_start = to_business_time(data.scheduled_start)
    return "\n".join(
        (
            opening,
            f"Servicio: {data.service_name}",
            f"Fecha: {_format_date(scheduled_start)}",
            f"Horario: {_format_time(scheduled_start)}",
            f"Sucursal: {_format_branch(data.branch)}",
            f"Duración: {_format_duration(data.duration_minutes)}",
            f"Estado: {_format_status(data.status)}",
            f"Precio: ${data.price:.2f} MXN",
        )
    )


def _from_appointment(
    appointment: ScheduledAppointment,
) -> AppointmentChangeNotificationData:
    snapshot = appointment.service_snapshot
    return AppointmentChangeNotificationData(
        email=appointment.email,
        phone=appointment.phone,
        service_name=snapshot.name,
        duration_minutes=snapshot.duration_minutes,
        price=snapshot.price,
        branch=appointment.branch,
        scheduled_start=appointment.scheduled_start,
        status=appointment.status,
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
