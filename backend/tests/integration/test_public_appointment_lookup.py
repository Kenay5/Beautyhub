"""T061 PostgreSQL evidence for exact private-code fingerprint lookup."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, insert

from backend.app.application.lookup_public_appointment import PublicAppointmentRecord
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    Appointment,
    PrivacyNoticeVersion,
    Service,
)
from backend.app.infrastructure.persistence.public_appointment_lookup_repository import (
    PostgresPublicAppointmentLookupReader,
)
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


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


@pytest.mark.integration
def test_t061_postgresql_lookup_returns_only_the_appointment_with_matching_digest(
    migrated_engine: Engine,
) -> None:
    fixture = _seed_two_appointments(migrated_engine)
    try:
        with migrated_engine.connect() as connection:
            reader = PostgresPublicAppointmentLookupReader(connection)
            result = reader.find_by_private_code_digest(fixture["first_digest"])
            missing = reader.find_by_private_code_digest(b"not-a-stored-fingerprint")

        assert result == PublicAppointmentRecord(
            service_name="Servicio T061 A",
            duration_minutes=60,
            price=Decimal("350.00"),
            branch="chiconcuac",
            scheduled_start=fixture["first_start"],
            status="scheduled",
            phone="5510000000",
            email="first@example.test",
        )
        assert missing is None
        assert "B" not in result.service_name
        assert not hasattr(result, "private_code_digest")
        assert not hasattr(result, "private_code_ciphertext")
    finally:
        _cleanup_fixture(migrated_engine, fixture)


def _seed_two_appointments(engine: Engine) -> dict[str, object]:
    marker = uuid4().hex
    now = datetime.now(tz=BUSINESS_TIME_ZONE).replace(microsecond=0)
    first_start = now + timedelta(days=10)
    second_start = first_start + timedelta(hours=2)
    first_digest = f"t061:first:{marker}".encode("ascii")
    second_digest = f"t061:second:{marker}".encode("ascii")

    with engine.begin() as connection:
        service_id = connection.execute(
            insert(Service)
            .values(
                name=f"Servicio T061 {marker}",
                description="Synthetic service for private-code lookup testing.",
                duration_minutes=60,
                price=Decimal("350.00"),
                is_active=True,
                available_chiconcuac=True,
                available_texcoco=True,
            )
            .returning(Service.service_id)
        ).scalar_one()
        notice_id = connection.execute(
            insert(PrivacyNoticeVersion)
            .values(
                version=f"synthetic-t061-{marker}",
                content="Synthetic privacy notice for private-code lookup testing.",
                published_at=now,
                valid_from=now,
            )
            .returning(PrivacyNoticeVersion.privacy_notice_version_id)
        ).scalar_one()
        connection.execute(
            insert(Appointment),
            [
                _appointment_values(
                    service_id=service_id,
                    notice_id=notice_id,
                    digest=first_digest,
                    service_name="Servicio T061 A",
                    first_name="Primera",
                    phone="5510000000",
                    email="first@example.test",
                    scheduled_start=first_start,
                    now=now,
                ),
                _appointment_values(
                    service_id=service_id,
                    notice_id=notice_id,
                    digest=second_digest,
                    service_name="Servicio T061 B",
                    first_name="Segunda",
                    phone="5510000001",
                    email="second@example.test",
                    scheduled_start=second_start,
                    now=now,
                ),
            ],
        )

    return {
        "service_id": service_id,
        "notice_id": notice_id,
        "first_digest": first_digest,
        "second_digest": second_digest,
        "first_start": first_start,
    }


def _appointment_values(
    *,
    service_id: int,
    notice_id: int,
    digest: bytes,
    service_name: str,
    first_name: str,
    phone: str,
    email: str,
    scheduled_start: datetime,
    now: datetime,
) -> dict[str, object]:
    return {
        "private_code_ciphertext": b"synthetic-private-code-ciphertext",
        "private_code_digest": digest,
        "first_name": first_name,
        "last_name": "Sintetica",
        "phone": phone,
        "email": email,
        "service_id": service_id,
        "service_snapshot_name": service_name,
        "service_snapshot_duration_minutes": 60,
        "service_snapshot_price": Decimal("350.00"),
        "branch": "chiconcuac",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_start + timedelta(hours=1),
        "status": "scheduled",
        "cancellation_reason": None,
        "origin": "public",
        "created_by_account_id": None,
        "privacy_notice_version_id": notice_id,
        "privacy_notice_accepted_at": now,
        "contact_processing_authorized": True,
        "adult_responsibility_declared": True,
    }


def _cleanup_fixture(engine: Engine, fixture: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(Appointment).where(Appointment.service_id == fixture["service_id"])
        )
        connection.execute(
            delete(Service).where(Service.service_id == fixture["service_id"])
        )
        connection.execute(
            delete(PrivacyNoticeVersion).where(
                PrivacyNoticeVersion.privacy_notice_version_id == fixture["notice_id"]
            )
        )
