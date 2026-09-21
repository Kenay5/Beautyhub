"""Protection for private administrative security-delivery intentions."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from backend.app.application.entropy import SecretGenerator
from backend.app.domain.authentication.admin_email_claim import (
    normalize_administrative_email_address,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


class SecurityNotificationDeliveryProtectionError(ValueError):
    """Raised when a delivery recipient or idempotency input is unsafe."""


@dataclass(frozen=True)
class ProtectedSecurityNotificationDeliveryRecipient:
    """Storage-safe representations for a temporary delivery recipient."""

    recipient_ciphertext: bytes
    recipient_key_version: str
    idempotency_key_digest: bytes


class SecurityNotificationDeliveryProtector:
    """Encrypt a recipient and derive a purpose-separated intent fingerprint."""

    def __init__(
        self,
        *,
        key_ring: CryptographyKeyRing,
        secret_generator: SecretGenerator,
    ) -> None:
        self._email_protector = AdministrativeEmailProtector(
            key_ring=key_ring,
            secret_generator=secret_generator,
        )
        self._idempotency_key = key_ring.derive("security-delivery-idempotency")

    def protect(
        self,
        *,
        event: str,
        template: str,
        recipient: str,
        idempotency_reference: str | None = None,
    ) -> ProtectedSecurityNotificationDeliveryRecipient:
        """Return no readable recipient and a stable key for one exact intent."""

        _require_identifier(event, "event")
        _require_identifier(template, "template")
        try:
            normalized_recipient = normalize_administrative_email_address(recipient)
        except ValueError as error:
            raise SecurityNotificationDeliveryProtectionError(
                "security delivery recipient is invalid."
            ) from error
        protected_email = self._email_protector.protect(normalized_recipient)
        if idempotency_reference is not None:
            _require_idempotency_reference(idempotency_reference)
        material_parts = [
            event.encode("ascii"),
            template.encode("ascii"),
            normalized_recipient.encode("ascii"),
        ]
        if idempotency_reference is not None:
            material_parts.append(idempotency_reference.encode("ascii"))
        material = b"\x00".join(material_parts)
        return ProtectedSecurityNotificationDeliveryRecipient(
            recipient_ciphertext=protected_email.email_ciphertext,
            recipient_key_version=protected_email.key_version,
            idempotency_key_digest=hmac.new(
                self._idempotency_key, material, hashlib.sha256
            ).digest(),
        )


def _require_identifier(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 100
        or not value[0].islower()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value)
    ):
        raise SecurityNotificationDeliveryProtectionError(
            f"security delivery {field_name} is invalid."
        )


def _require_idempotency_reference(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 100
        or not value
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_:" for character in value)
    ):
        raise SecurityNotificationDeliveryProtectionError(
            "security delivery idempotency reference is invalid."
        )
