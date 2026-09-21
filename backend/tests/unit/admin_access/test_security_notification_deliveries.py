"""T017 unit evidence for private, idempotent security-delivery intents."""

from __future__ import annotations

import base64

import pytest

from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
    StoredSecurityNotificationDelivery,
)
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.authentication.security_notification_delivery import (
    FAILED_SECURITY_NOTIFICATION_DELIVERY_STATUS,
    SANITIZED_SECURITY_DELIVERY_FAILURE,
    SecurityNotificationDelivery,
    SecurityNotificationDeliveryInvariantError,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x01" * 32).decode("ascii")),
            key_version="v1",
        )
    )


class InMemoryDeliveryStore:
    def __init__(self) -> None:
        self.deliveries: dict[bytes, SecurityNotificationDelivery] = {}

    def record_or_get(
        self, *, delivery: SecurityNotificationDelivery
    ) -> StoredSecurityNotificationDelivery:
        existing = self.deliveries.get(delivery.idempotency_key_digest)
        if existing is not None:
            return StoredSecurityNotificationDelivery(delivery_id=1, status=existing.status)
        self.deliveries[delivery.idempotency_key_digest] = delivery
        return StoredSecurityNotificationDelivery(delivery_id=1, status=delivery.status)


def test_t017_encrypts_the_temporary_recipient_and_derives_one_exact_intent_key() -> None:
    protector = SecurityNotificationDeliveryProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator(
            [b"\x01" * 12, b"\x02" * 12, b"\x03" * 12]
        ),
    )

    first = protector.protect(
        event="staff_invitation",
        template="staff_invitation_link",
        recipient="Synthetic.Staff@Example.TEST",
    )
    repeated = protector.protect(
        event="staff_invitation",
        template="staff_invitation_link",
        recipient="synthetic.staff@example.test",
    )
    different_template = protector.protect(
        event="staff_invitation",
        template="security_notice",
        recipient="synthetic.staff@example.test",
    )

    assert b"synthetic.staff@example.test" not in first.recipient_ciphertext
    assert first.recipient_ciphertext != repeated.recipient_ciphertext
    assert first.idempotency_key_digest == repeated.idempotency_key_digest
    assert first.idempotency_key_digest != different_template.idempotency_key_digest
    assert len(first.idempotency_key_digest) == 32


def test_t045_lock_event_reference_distinguishes_future_notice_intents() -> None:
    protector = SecurityNotificationDeliveryProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator(
            [b"\x04" * 12, b"\x05" * 12, b"\x06" * 12]
        ),
    )

    first = protector.protect(
        event="account_locked",
        template="account_locked_notice",
        recipient="synthetic.owner@example.test",
        idempotency_reference="credential_failure:41",
    )
    repeated = protector.protect(
        event="account_locked",
        template="account_locked_notice",
        recipient="synthetic.owner@example.test",
        idempotency_reference="credential_failure:41",
    )
    later_lock = protector.protect(
        event="account_locked",
        template="account_locked_notice",
        recipient="synthetic.owner@example.test",
        idempotency_reference="credential_failure:82",
    )

    assert first.idempotency_key_digest == repeated.idempotency_key_digest
    assert first.idempotency_key_digest != later_lock.idempotency_key_digest


def test_t017_reuses_the_original_record_for_a_repeated_intent() -> None:
    store = InMemoryDeliveryStore()
    recorder = RecordSecurityNotificationDelivery(
        store=store,
        protector=SecurityNotificationDeliveryProtector(
            key_ring=_key_ring(),
            secret_generator=SequenceSecretGenerator([b"\x03" * 12, b"\x04" * 12]),
        ),
    )

    first = recorder.record(
        event="password_changed",
        template="password_changed_notice",
        recipient="synthetic.owner@example.test",
    )
    repeated = recorder.record(
        event="password_changed",
        template="password_changed_notice",
        recipient="synthetic.owner@example.test",
    )

    assert first == repeated
    assert len(store.deliveries) == 1
    persisted = next(iter(store.deliveries.values()))
    assert "recipient" not in persisted.__dataclass_fields__
    assert "token" not in persisted.__dataclass_fields__


@pytest.mark.parametrize(
    ("status", "sanitized_error"),
    (
        ("failed", "provider password=secret"),
        ("pending", SANITIZED_SECURITY_DELIVERY_FAILURE),
    ),
)
def test_t017_rejects_unsanitized_or_inconsistent_error_data(
    status: str, sanitized_error: str
) -> None:
    with pytest.raises(SecurityNotificationDeliveryInvariantError):
        SecurityNotificationDelivery(
            event="password_changed",
            recipient_ciphertext=b"ciphertext",
            recipient_key_version="v1",
            template="password_changed_notice",
            idempotency_key_digest=b"\x01" * 32,
            status=status,  # type: ignore[arg-type]
            sanitized_error=sanitized_error,
        )


def test_t017_allows_only_the_controlled_failure_marker() -> None:
    delivery = SecurityNotificationDelivery(
        event="password_changed",
        recipient_ciphertext=b"ciphertext",
        recipient_key_version="v1",
        template="password_changed_notice",
        idempotency_key_digest=b"\x01" * 32,
        status=FAILED_SECURITY_NOTIFICATION_DELIVERY_STATUS,
        sanitized_error=SANITIZED_SECURITY_DELIVERY_FAILURE,
    )

    assert delivery.sanitized_error == SANITIZED_SECURITY_DELIVERY_FAILURE
