"""T084A unit evidence for transactional notification delivery states."""

from __future__ import annotations

import pytest

from backend.app.domain.notification_delivery import (
    ACCEPTED_DELIVERY_STATUS,
    DELIVERED_DELIVERY_STATUS,
    FAILED_DELIVERY_STATUS,
    PENDING_DELIVERY_STATUS,
    NotificationDeliveryTransitionError,
    transition_notification_delivery_status,
)


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    (
        (PENDING_DELIVERY_STATUS, ACCEPTED_DELIVERY_STATUS),
        (PENDING_DELIVERY_STATUS, FAILED_DELIVERY_STATUS),
        (ACCEPTED_DELIVERY_STATUS, DELIVERED_DELIVERY_STATUS),
        (ACCEPTED_DELIVERY_STATUS, FAILED_DELIVERY_STATUS),
    ),
)
def test_t084a_allows_only_approved_delivery_transitions(
    current_status: str,
    next_status: str,
) -> None:
    assert transition_notification_delivery_status(
        current_status=current_status,
        next_status=next_status,
    ) == next_status


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    (
        (PENDING_DELIVERY_STATUS, DELIVERED_DELIVERY_STATUS),
        (ACCEPTED_DELIVERY_STATUS, PENDING_DELIVERY_STATUS),
        (DELIVERED_DELIVERY_STATUS, FAILED_DELIVERY_STATUS),
        (FAILED_DELIVERY_STATUS, ACCEPTED_DELIVERY_STATUS),
        (FAILED_DELIVERY_STATUS, PENDING_DELIVERY_STATUS),
        (DELIVERED_DELIVERY_STATUS, DELIVERED_DELIVERY_STATUS),
        ("unknown", PENDING_DELIVERY_STATUS),
        (PENDING_DELIVERY_STATUS, "unknown"),
    ),
)
def test_t084a_rejects_invalid_or_terminal_delivery_transitions(
    current_status: str,
    next_status: str,
) -> None:
    with pytest.raises(NotificationDeliveryTransitionError):
        transition_notification_delivery_status(
            current_status=current_status,
            next_status=next_status,
        )
