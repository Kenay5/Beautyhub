"""T069 PostgreSQL evidence for overlapping public access restrictions."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, select

from backend.app.application.clock import FixedClock
from backend.app.application.public_access_restrictions import (
    CombinePublicAppointmentRestrictions,
)
from backend.app.application.public_credential_failures import (
    RecordPublicCredentialFailure,
)
from backend.app.application.public_request_limit import (
    LimitPublicAppointmentRequests,
    PublicRequestRateLimitError,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import PublicRequestEvent
from backend.app.infrastructure.persistence.public_credential_failure_repository import (
    PostgresPublicCredentialFailureStore,
)
from backend.app.infrastructure.persistence.public_request_limit_repository import (
    PostgresPublicRequestWindowStore,
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
def test_t069_postgresql_applies_the_later_overlapping_expiry_without_writes(
    migrated_engine: Engine,
) -> None:
    fingerprint = f"t069:{uuid4().hex}".encode("ascii")
    now = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
    try:
        with migrated_engine.begin() as connection:
            request_store = PostgresPublicRequestWindowStore(connection)
            credential_store = PostgresPublicCredentialFailureStore(connection)
            general_limiter = LimitPublicAppointmentRequests(
                store=request_store,
                clock=FixedClock(now),
                subject_fingerprint=fingerprint,
            )
            for _ in range(10):
                general_limiter.ensure_allowed("appointment_lookup")

            credential_recorder = RecordPublicCredentialFailure(
                store=credential_store,
                clock=FixedClock(now + timedelta(minutes=5)),
            )
            for _ in range(5):
                credential_recorder.record_failure(subject_fingerprint=fingerprint)

        with migrated_engine.begin() as connection:
            request_store = PostgresPublicRequestWindowStore(connection)
            credential_store = PostgresPublicCredentialFailureStore(connection)
            guard = CombinePublicAppointmentRestrictions(
                request_store=request_store,
                credential_store=credential_store,
                clock=FixedClock(now + timedelta(minutes=6)),
                subject_fingerprint=fingerprint,
            )
            count_before = connection.execute(
                select(func.count())
                .select_from(PublicRequestEvent)
                .where(PublicRequestEvent.subject_fingerprint == fingerprint)
            ).scalar_one()

            with pytest.raises(PublicRequestRateLimitError) as raised:
                guard.ensure_allowed("appointment_lookup")

            count_after = connection.execute(
                select(func.count())
                .select_from(PublicRequestEvent)
                .where(PublicRequestEvent.subject_fingerprint == fingerprint)
            ).scalar_one()

        assert raised.value.denied_until == now + timedelta(minutes=20)
        assert count_before == 16
        assert count_after == count_before
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(
                delete(PublicRequestEvent).where(
                    PublicRequestEvent.subject_fingerprint == fingerprint
                )
            )
