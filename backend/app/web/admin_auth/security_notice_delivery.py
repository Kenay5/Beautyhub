"""Post-commit dispatch for approved administrative security notices."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import Engine

from backend.app.application.admin_access.account_security import (
    SecurityNotificationDispatch,
)
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.infrastructure.email_simulator import EmailSimulatorUncertainOutcome
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)


_LOGGER = logging.getLogger(__name__)
_NOTICE_CONTENT = {
    ("account_locked", "account_locked_notice"): (
        "Se bloqueó temporalmente una cuenta administrativa tras varios intentos "
        "fallidos. Si no fuiste tú, revisa la seguridad de la cuenta."
    ),
    ("staff_invited", "staff_invitation_notice"): "Se registró una invitación para una cuenta de personal.",
    ("staff_activated", "staff_activation_notice"): "Una cuenta de personal completó su activación.",
}


def deliver_security_notices(
    *,
    engine: Engine,
    email_sender: TransactionalNotificationPort,
    notices: Iterable[SecurityNotificationDispatch],
) -> None:
    """Attempt committed, server-targeted notices without changing business state."""

    for notice in notices:
        content = _NOTICE_CONTENT.get((notice.event, notice.template))
        if content is None:
            raise ValueError("administrative security notice template is invalid.")
        try:
            with engine.begin() as connection:
                claimed = PostgresSecurityNotificationDeliveryStore(
                    connection
                ).claim_for_dispatch(delivery_id=notice.delivery_id)
        except Exception:
            _LOGGER.error("administrative security notice could not be claimed")
            continue
        if not claimed:
            continue
        try:
            result = email_sender.send(
                OutboundNotification(
                    channel=EMAIL_CHANNEL,
                    recipient=notice.recipient,
                    content=content,
                )
            )
            outcome = (
                result.outcome
                if result.channel == EMAIL_CHANNEL
                and result.outcome in {"accepted", "failed", "uncertain"}
                else "failed"
            )
        except EmailSimulatorUncertainOutcome:
            outcome = "uncertain"
        except Exception:
            outcome = "failed"

        try:
            with engine.begin() as connection:
                PostgresSecurityNotificationDeliveryStore(
                    connection
                ).record_immediate_result(
                    delivery_id=notice.delivery_id,
                    outcome=outcome,
                )
        except Exception:
            _LOGGER.error("administrative security notice status was not recorded")
