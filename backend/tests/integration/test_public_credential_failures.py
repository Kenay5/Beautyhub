"""T065 PostgreSQL evidence for persisted public credential failure windows."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, select

from backend.app.application.clock import FixedClock
from backend.app.application.public_credential_failures import (
    PUBLIC_CREDENTIAL_BLOCK_RESULT,
    PUBLIC_CREDENTIAL_EVENT_CATEGORY,
    PUBLIC_CREDENTIAL_FAILURE_RESULT,
    RecordPublicCredentialFailure,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import PublicRequestEvent
from backend.app.infrastructure.persistence.public_credential_failure_repository import (
    PostgresPublicCredentialFailureStore,
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
def test_t065_postgresql_persists_five_failures_and_one_block_without_raw_ip(
    migrated_engine: Engine,
) -> None:
    fingerprint = f"t065:{uuid4().hex}".encode("ascii")
    now = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
    try:
        with migrated_engine.begin() as connection:
            recorder = RecordPublicCredentialFailure(
                store=PostgresPublicCredentialFailureStore(connection),
                clock=FixedClock(now),
            )
            results = tuple(
                recorder.record_failure(subject_fingerprint=fingerprint)
                for _ in range(5)
            )

        with migrated_engine.connect() as connection:
            rows = connection.execute(
                select(
                    PublicRequestEvent.category,
                    PublicRequestEvent.result,
                    PublicRequestEvent.subject_fingerprint,
                    PublicRequestEvent.expires_at,
                )
                .where(PublicRequestEvent.subject_fingerprint == fingerprint)
                .order_by(PublicRequestEvent.public_request_event_id)
            ).all()

        assert results[-1].block_expires_at == now + timedelta(minutes=15)
        assert [(row.category, row.result) for row in rows] == [
            (PUBLIC_CREDENTIAL_EVENT_CATEGORY, PUBLIC_CREDENTIAL_FAILURE_RESULT),
            (PUBLIC_CREDENTIAL_EVENT_CATEGORY, PUBLIC_CREDENTIAL_FAILURE_RESULT),
            (PUBLIC_CREDENTIAL_EVENT_CATEGORY, PUBLIC_CREDENTIAL_FAILURE_RESULT),
            (PUBLIC_CREDENTIAL_EVENT_CATEGORY, PUBLIC_CREDENTIAL_FAILURE_RESULT),
            (PUBLIC_CREDENTIAL_EVENT_CATEGORY, PUBLIC_CREDENTIAL_FAILURE_RESULT),
            (PUBLIC_CREDENTIAL_EVENT_CATEGORY, PUBLIC_CREDENTIAL_BLOCK_RESULT),
        ]
        assert {row.subject_fingerprint for row in rows} == {fingerprint}
        assert {row.expires_at for row in rows} == {now + timedelta(minutes=15)}
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(
                delete(PublicRequestEvent).where(
                    PublicRequestEvent.subject_fingerprint == fingerprint
                )
            )
