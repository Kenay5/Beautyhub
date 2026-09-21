"""T067 PostgreSQL evidence for the public read request limit."""

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
from backend.app.application.public_request_limit import (
    LimitPublicReadRequests,
    PublicRequestRateLimitError,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import PublicRequestEvent
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
def test_t067_postgresql_accepts_60_rejects_61_without_extending_window(
    migrated_engine: Engine,
) -> None:
    fingerprint = f"t067:{uuid4().hex}".encode("ascii")
    now = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
    try:
        with migrated_engine.begin() as connection:
            store = PostgresPublicRequestWindowStore(connection)
            limiter = LimitPublicReadRequests(
                store=store,
                clock=FixedClock(now),
                subject_fingerprint=fingerprint,
            )
            for _ in range(30):
                limiter.ensure_allowed("service_catalog")
                limiter.ensure_allowed("availability")
            with pytest.raises(PublicRequestRateLimitError):
                limiter.ensure_allowed("availability")

        with migrated_engine.connect() as connection:
            count_before_expiry, latest_expiry = connection.execute(
                select(
                    func.count(),
                    func.max(PublicRequestEvent.expires_at),
                ).where(PublicRequestEvent.subject_fingerprint == fingerprint)
            ).one()

        with migrated_engine.begin() as connection:
            at_boundary = LimitPublicReadRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=FixedClock(now + timedelta(seconds=60)),
                subject_fingerprint=fingerprint,
            )
            at_boundary.ensure_allowed("service_catalog")

        assert count_before_expiry == 60
        assert latest_expiry == now + timedelta(seconds=60)
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(
                delete(PublicRequestEvent).where(
                    PublicRequestEvent.subject_fingerprint == fingerprint
                )
            )
