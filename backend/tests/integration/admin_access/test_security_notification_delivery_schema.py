"""T017 PostgreSQL evidence for private idempotent security-delivery storage."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, inspect, select
from sqlalchemy.exc import DBAPIError

from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import SecurityNotificationDelivery
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_test_database_url,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            alembic_config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")
        yield engine
    finally:
        engine.dispose()


def _recorder(connection, nonces: list[bytes]) -> RecordSecurityNotificationDelivery:
    key_ring = CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x02" * 32).decode("ascii")),
            key_version="v1",
        )
    )
    return RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(
            key_ring=key_ring,
            secret_generator=SequenceSecretGenerator(nonces),
        ),
    )


@pytest.mark.integration
def test_t017_persists_only_an_encrypted_recipient_and_one_idempotent_intent(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert "security_notification_deliveries" in inspector.get_table_names()
    columns = {
        column["name"]
        for column in inspector.get_columns("security_notification_deliveries")
    }
    assert columns == {
        "security_notification_delivery_id",
        "event",
        "recipient_ciphertext",
        "recipient_key_version",
        "template",
        "idempotency_key_digest",
        "status",
        "sanitized_error",
        "created_at",
        "updated_at",
    }
    assert not {
        "recipient",
        "email",
        "token",
        "link",
        "password",
        "provider_error",
        "external_reference",
    } & columns

    digest: bytes | None = None
    try:
        with migrated_engine.begin() as connection:
            recorder = _recorder(connection, [b"\x05" * 12, b"\x06" * 12])
            first = recorder.record(
                event="staff_invitation",
                template="staff_invitation_link",
                recipient="synthetic.staff@example.test",
            )
            repeated = recorder.record(
                event="staff_invitation",
                template="staff_invitation_link",
                recipient="synthetic.staff@example.test",
            )
            assert first == repeated
            row = connection.execute(
                select(
                    SecurityNotificationDelivery.recipient_ciphertext,
                    SecurityNotificationDelivery.recipient_key_version,
                    SecurityNotificationDelivery.idempotency_key_digest,
                    SecurityNotificationDelivery.status,
                    SecurityNotificationDelivery.sanitized_error,
                ).where(
                    SecurityNotificationDelivery.security_notification_delivery_id
                    == first.delivery_id
                )
            ).one()
            digest = row.idempotency_key_digest
            assert b"synthetic.staff@example.test" not in row.recipient_ciphertext
            assert row.recipient_key_version == "v1"
            assert row.status == "pending"
            assert row.sanitized_error is None

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        SecurityNotificationDelivery.__table__.insert().values(
                            event="staff_invitation",
                            recipient_ciphertext=b"not-encrypted",
                            recipient_key_version="v1",
                            template="staff_invitation_link",
                            idempotency_key_digest=b"short",
                            status="pending",
                            sanitized_error=None,
                        )
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        SecurityNotificationDelivery.__table__.insert().values(
                            event="staff_invitation",
                            recipient_ciphertext=b"synthetic-ciphertext",
                            recipient_key_version="v1",
                            template="staff_invitation_link",
                            idempotency_key_digest=b"\x07" * 32,
                            status="failed",
                            sanitized_error="provider token=secret",
                        )
                    )
            connection.execute(
                SecurityNotificationDelivery.__table__.insert().values(
                    event="staff_invitation",
                    recipient_ciphertext=None,
                    recipient_key_version=None,
                    template="security_notice",
                    idempotency_key_digest=b"\x08" * 32,
                    status="accepted",
                    sanitized_error=None,
                )
            )

        with migrated_engine.connect() as connection:
            count = connection.execute(
                select(func.count())
                .select_from(SecurityNotificationDelivery)
                .where(SecurityNotificationDelivery.idempotency_key_digest == digest)
            ).scalar_one()
        assert count == 1
    finally:
        if digest is not None:
            with migrated_engine.begin() as connection:
                connection.execute(
                    delete(SecurityNotificationDelivery).where(
                        SecurityNotificationDelivery.idempotency_key_digest.in_(
                            (digest, b"\x08" * 32)
                        )
                    )
                )


@pytest.mark.integration
def test_t098_late_failure_cannot_revert_an_accepted_security_notice(
    migrated_engine: Engine,
) -> None:
    idempotency_digest: bytes | None = None
    try:
        with migrated_engine.begin() as connection:
            delivery = _recorder(connection, [b"\x19" * 12]).record(
                event="password_changed",
                template="password_changed_notice",
                recipient="synthetic.owner@example.test",
                idempotency_reference="t098_late_provider_result",
            )
            idempotency_digest = connection.execute(
                select(SecurityNotificationDelivery.idempotency_key_digest).where(
                    SecurityNotificationDelivery.security_notification_delivery_id
                    == delivery.delivery_id
                )
            ).scalar_one()
            store = PostgresSecurityNotificationDeliveryStore(connection)
            assert store.claim_for_dispatch(delivery_id=delivery.delivery_id)
            store.record_immediate_result(
                delivery_id=delivery.delivery_id,
                outcome="accepted",
            )

        with migrated_engine.begin() as connection:
            with pytest.raises(RuntimeError):
                PostgresSecurityNotificationDeliveryStore(
                    connection
                ).record_immediate_result(
                    delivery_id=delivery.delivery_id,
                    outcome="failed",
                )

        with migrated_engine.connect() as connection:
            assert connection.execute(
                select(SecurityNotificationDelivery.status).where(
                    SecurityNotificationDelivery.security_notification_delivery_id
                    == delivery.delivery_id
                )
            ).scalar_one() == "accepted"
    finally:
        if idempotency_digest is not None:
            with migrated_engine.begin() as connection:
                connection.execute(
                    delete(SecurityNotificationDelivery).where(
                        SecurityNotificationDelivery.idempotency_key_digest
                        == idempotency_digest
                    )
                )
