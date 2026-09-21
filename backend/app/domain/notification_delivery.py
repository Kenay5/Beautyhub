"""Valid lifecycle transitions for one transactional notification delivery."""

from __future__ import annotations

from typing import Final, Literal, TypeAlias


NotificationDeliveryStatus: TypeAlias = Literal[
    "pending", "accepted", "delivered", "failed"
]

PENDING_DELIVERY_STATUS: Final[NotificationDeliveryStatus] = "pending"
ACCEPTED_DELIVERY_STATUS: Final[NotificationDeliveryStatus] = "accepted"
DELIVERED_DELIVERY_STATUS: Final[NotificationDeliveryStatus] = "delivered"
FAILED_DELIVERY_STATUS: Final[NotificationDeliveryStatus] = "failed"

_VALID_TRANSITIONS: Final[dict[NotificationDeliveryStatus, frozenset[NotificationDeliveryStatus]]] = {
    PENDING_DELIVERY_STATUS: frozenset(
        {ACCEPTED_DELIVERY_STATUS, FAILED_DELIVERY_STATUS}
    ),
    ACCEPTED_DELIVERY_STATUS: frozenset(
        {DELIVERED_DELIVERY_STATUS, FAILED_DELIVERY_STATUS}
    ),
    DELIVERED_DELIVERY_STATUS: frozenset(),
    FAILED_DELIVERY_STATUS: frozenset(),
}


class NotificationDeliveryTransitionError(ValueError):
    """Raised when a delivery attempts a transition outside its lifecycle."""


def transition_notification_delivery_status(
    *,
    current_status: str,
    next_status: str,
) -> NotificationDeliveryStatus:
    """Allow only the provider lifecycle approved for one delivery attempt."""

    current = _require_status(current_status)
    next_value = _require_status(next_status)
    if next_value not in _VALID_TRANSITIONS[current]:
        raise NotificationDeliveryTransitionError(
            "notification delivery transition is not permitted."
        )
    return next_value


def _require_status(value: str) -> NotificationDeliveryStatus:
    if value not in _VALID_TRANSITIONS:
        raise NotificationDeliveryTransitionError(
            "notification delivery status is invalid."
        )
    return value  # type: ignore[return-value]
