"""Application boundary for durable administrative security-delivery intents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.app.domain.authentication.security_notification_delivery import (
    PENDING_SECURITY_NOTIFICATION_DELIVERY_STATUS,
    SecurityNotificationDelivery,
    SecurityNotificationDeliveryStatus,
)
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)


@dataclass(frozen=True)
class StoredSecurityNotificationDelivery:
    """The non-sensitive result of recording one delivery intent."""

    delivery_id: int
    status: SecurityNotificationDeliveryStatus


class SecurityNotificationDeliveryStore(Protocol):
    """Persist or recover the one durable record for an idempotency key."""

    def record_or_get(
        self, *, delivery: SecurityNotificationDelivery
    ) -> StoredSecurityNotificationDelivery:
        """Return the original record when the same intent is repeated."""


class RecordSecurityNotificationDelivery:
    """Create one private delivery intent without dispatching a provider call."""

    def __init__(
        self,
        *,
        store: SecurityNotificationDeliveryStore,
        protector: SecurityNotificationDeliveryProtector,
    ) -> None:
        self._store = store
        self._protector = protector

    def record(
        self,
        *,
        event: str,
        template: str,
        recipient: str,
        idempotency_reference: str | None = None,
    ) -> StoredSecurityNotificationDelivery:
        """Persist exactly one encrypted recipient for an exact delivery intent."""

        protected = self._protector.protect(
            event=event,
            template=template,
            recipient=recipient,
            idempotency_reference=idempotency_reference,
        )
        return self._store.record_or_get(
            delivery=SecurityNotificationDelivery(
                event=event,
                recipient_ciphertext=protected.recipient_ciphertext,
                recipient_key_version=protected.recipient_key_version,
                template=template,
                idempotency_key_digest=protected.idempotency_key_digest,
                status=PENDING_SECURITY_NOTIFICATION_DELIVERY_STATUS,
            )
        )
