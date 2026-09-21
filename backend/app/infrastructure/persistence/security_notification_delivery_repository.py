"""PostgreSQL persistence for private administrative security-delivery intents."""

from __future__ import annotations

from sqlalchemy import Connection, select
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
