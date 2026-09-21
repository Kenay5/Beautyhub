"""T066 PostgreSQL evidence for applying and expiring credential blocks."""

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
from backend.app.application.public_credential_failures import (
    EnsurePublicCredentialAccess,
    PublicCredentialBlockedError,
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
def test_t066_postgresql_block_rejects_without_writes_and_expires_exactly(
    migrated_engine: Engine,
) -> None:
    blocked_fingerprint = f"t066-blocked:{uuid4().hex}".encode("ascii")
    other_fingerprint = f"t066-other:{uuid4().hex}".encode("ascii")
    now = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
    try:
        with migrated_engine.begin() as connection:
            store = PostgresPublicCredentialFailureStore(connection)
            recorder = RecordPublicCredentialFailure(
                store=store,
                clock=FixedClock(now),
            )
            for _ in range(5):
                recorder.record_failure(subject_fingerprint=blocked_fingerprint)

        with migrated_engine.begin() as connection:
            store = PostgresPublicCredentialFailureStore(connection)
            blocked_guard = EnsurePublicCredentialAccess(
                store=store,
                clock=FixedClock(now + timedelta(minutes=1)),
            )
            with pytest.raises(PublicCredentialBlockedError):
                blocked_guard.ensure_allowed(subject_fingerprint=blocked_fingerprint)
            with pytest.raises(PublicCredentialBlockedError):
                RecordPublicCredentialFailure(
                    store=store,
                    clock=FixedClock(now + timedelta(minutes=1)),
                ).record_failure(subject_fingerprint=blocked_fingerprint)

            blocked_guard.ensure_allowed(subject_fingerprint=other_fingerprint)
            event_count = connection.execute(
                select(func.count())
                .select_from(PublicRequestEvent)
                .where(PublicRequestEvent.subject_fingerprint == blocked_fingerprint)
            ).scalar_one()

        with migrated_engine.connect() as connection:
            expired_guard = EnsurePublicCredentialAccess(
                store=PostgresPublicCredentialFailureStore(connection),
                clock=FixedClock(now + timedelta(minutes=15)),
            )
            expired_guard.ensure_allowed(subject_fingerprint=blocked_fingerprint)

        assert event_count == 6
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(
                delete(PublicRequestEvent).where(
                    PublicRequestEvent.subject_fingerprint.in_(
                        (blocked_fingerprint, other_fingerprint)
                    )
                )
            )
