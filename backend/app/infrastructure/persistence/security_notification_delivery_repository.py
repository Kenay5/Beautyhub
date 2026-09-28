"""PostgreSQL persistence for private administrative security-delivery intents."""

from __future__ import annotations

from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.postgresql import insert

from backend.app.application.admin_access.security_notification_deliveries import (
    SecurityNotificationDeliveryStore,
    StoredSecurityNotificationDelivery,
)
from backend.app.domain.authentication.security_notification_delivery import (
    SecurityNotificationDelivery,
)
from backend.app.infrastructure.persistence.models import SecurityNotificationDelivery as SecurityNotificationDeliveryModel


class PostgresSecurityNotificationDeliveryStore(SecurityNotificationDeliveryStore):
    """Store one delivery intent per opaque idempotency key."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def record_or_get(
        self, *, delivery: SecurityNotificationDelivery
    ) -> StoredSecurityNotificationDelivery:
        """Insert once, then return the existing durable result on repetition."""

        self._connection.execute(
            insert(SecurityNotificationDeliveryModel)
            .values(
                event=delivery.event,
                recipient_ciphertext=delivery.recipient_ciphertext,
                recipient_key_version=delivery.recipient_key_version,
                template=delivery.template,
                idempotency_key_digest=delivery.idempotency_key_digest,
                status=delivery.status,
                sanitized_error=delivery.sanitized_error,
            )
            .on_conflict_do_nothing(
                index_elements=(
                    SecurityNotificationDeliveryModel.idempotency_key_digest,
                )
            )
        )
        row = self._connection.execute(
            select(
                SecurityNotificationDeliveryModel.security_notification_delivery_id,
                SecurityNotificationDeliveryModel.status,
            ).where(
                SecurityNotificationDeliveryModel.idempotency_key_digest
                == delivery.idempotency_key_digest
            )
        ).one()
        return StoredSecurityNotificationDelivery(
            delivery_id=row.security_notification_delivery_id,
            status=row.status,
        )

    def record_immediate_result(self, *, delivery_id: int, outcome: str) -> None:
        """Keep a confirmed simulator/provider outcome without reverting its action."""

        if outcome not in {"accepted", "failed", "uncertain"}:
            raise ValueError("security delivery outcome is invalid.")
        values = {
            "status": outcome,
            "sanitized_error": "security delivery failed." if outcome == "failed" else None,
        }
        if outcome == "accepted":
            values["recipient_ciphertext"] = None
            values["recipient_key_version"] = None
        updated = self._connection.execute(
            update(SecurityNotificationDeliveryModel)
            .where(
                SecurityNotificationDeliveryModel.security_notification_delivery_id
                == delivery_id,
                SecurityNotificationDeliveryModel.status.in_(("pending", "uncertain")),
            )
            .values(**values)
        )
        if updated.rowcount != 1:
            raise RuntimeError("security delivery intent is no longer pending.")

    def claim_for_dispatch(self, *, delivery_id: int) -> bool:
        """Atomically reserve one pending intent so concurrent/repeated dispatches skip it."""

        updated = self._connection.execute(
            update(SecurityNotificationDeliveryModel)
            .where(
                SecurityNotificationDeliveryModel.security_notification_delivery_id
                == delivery_id,
                SecurityNotificationDeliveryModel.status == "pending",
            )
            .values(status="uncertain")
        )
        return updated.rowcount == 1
