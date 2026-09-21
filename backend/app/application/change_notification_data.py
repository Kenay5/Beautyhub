"""Provider-neutral data committed for appointment change notifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from backend.app.application.transactional_notifications import NotificationChannel
from backend.app.domain.notification_delivery import NotificationDeliveryStatus


@dataclass(frozen=True)
class ChangeNotificationDelivery:
    """One durable delivery intent created with an appointment change."""

    delivery_id: int
    channel: NotificationChannel
    status: NotificationDeliveryStatus


@dataclass(frozen=True)
class AppointmentChangeNotificationData:
    """Minimum committed appointment data needed by ordinary change messages."""

    email: str = field(repr=False)
    phone: str = field(repr=False)
    service_name: str
    duration_minutes: int
    price: Decimal
    branch: str
    scheduled_start: datetime
    status: str
