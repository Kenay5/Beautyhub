"""T015 PostgreSQL evidence for private, row-serialized moving limits."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, inspect, select
from sqlalchemy.exc import DBAPIError

from backend.app.application.admin_access.rate_limit import (
    ReserveAdministrativeRateLimit,
)
from backend.app.application.clock import FixedClock
from backend.app.infrastructure.persistence.admin_rate_limit_repository import (
    PostgresAdministrativeRateLimitStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import RateLimitEvent, RateLimitGuard
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
CATEGORY = "authentication_recovery_lost_factor"


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


def _reserve(
    connection,
    *,
    subject_fingerprint: bytes,
    request_fingerprint: bytes,
    current_time: datetime = NOW,
) -> bool:
    return ReserveAdministrativeRateLimit(
        store=PostgresAdministrativeRateLimitStore(connection),
        clock=FixedClock(current_time),
    ).reserve(
        category=CATEGORY,
        subject_fingerprint=subject_fingerprint,
        request_fingerprint=request_fingerprint,
    )


@pytest.mark.integration
def test_t015_persists_only_fingerprints_and_idempotent_requests(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert {"rate_limit_events", "rate_limit_guards"}.issubset(
        inspector.get_table_names()
    )
    all_columns = {
        column["name"]
        for table_name in ("rate_limit_events", "rate_limit_guards")
        for column in inspector.get_columns(table_name)
    }
    assert not {"ip_address", "ip", "email", "password", "token"} & all_columns

    subject = b"t015-private-subject".ljust(32, b"_")
    request = b"t015-idempotent-request".ljust(32, b"_")
    try:
        with migrated_engine.begin() as connection:
            assert _reserve(
                connection,
                subject_fingerprint=subject,
                request_fingerprint=request,
            )
            assert _reserve(
                connection,
                subject_fingerprint=subject,
                request_fingerprint=request,
            )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        RateLimitEvent.__table__.insert().values(
                            category="not_approved",
                            subject_fingerprint=b"x" * 32,
                            request_fingerprint=b"y" * 32,
                            occurred_at=NOW,
                        )
                    )

        with migrated_engine.connect() as connection:
            event_count = connection.execute(
                select(func.count())
                .select_from(RateLimitEvent)
                .where(
                    RateLimitEvent.category == CATEGORY,
                    RateLimitEvent.subject_fingerprint == subject,
                )
            ).scalar_one()
        assert event_count == 1
    finally:
        _delete_subject(migrated_engine, subject)


@pytest.mark.integration
def test_t015_serializes_the_twentieth_shared_limit_reservation(
    migrated_engine: Engine,
) -> None:
    subject = b"t015-contested-subject".ljust(32, b"_")
    try:
        with migrated_engine.begin() as connection:
            for marker in range(19):
                assert _reserve(
                    connection,
                    subject_fingerprint=subject,
                    request_fingerprint=bytes([marker]) * 32,
                )

        outcomes = _run_concurrently(
            (
                lambda: _attempt_reservation(migrated_engine, subject, b"a" * 32),
                lambda: _attempt_reservation(migrated_engine, subject, b"b" * 32),
            )
        )
        assert sorted(outcomes) == ["accepted", "rejected"]

        with migrated_engine.connect() as connection:
            event_count = connection.execute(
                select(func.count())
                .select_from(RateLimitEvent)
                .where(
                    RateLimitEvent.category == CATEGORY,
                    RateLimitEvent.subject_fingerprint == subject,
                )
            ).scalar_one()
        assert event_count == 20

        with migrated_engine.begin() as connection:
            assert _reserve(
                connection,
                subject_fingerprint=subject,
                request_fingerprint=b"c" * 32,
                current_time=NOW + timedelta(minutes=15),
            )
    finally:
        _delete_subject(migrated_engine, subject)


def _run_concurrently(workers: tuple[Callable[[], str], ...]) -> list[str]:
    barrier = Barrier(len(workers))

    def synchronized(worker: Callable[[], str]) -> str:
        barrier.wait(timeout=10)
        return worker()

    with ThreadPoolExecutor(max_workers=len(workers)) as executor:
        return list(executor.map(synchronized, workers))


def _attempt_reservation(
    engine: Engine, subject_fingerprint: bytes, request_fingerprint: bytes
) -> str:
    with engine.begin() as connection:
        accepted = _reserve(
            connection,
            subject_fingerprint=subject_fingerprint,
            request_fingerprint=request_fingerprint,
        )
    return "accepted" if accepted else "rejected"


def _delete_subject(engine: Engine, subject_fingerprint: bytes) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(RateLimitEvent).where(
                RateLimitEvent.subject_fingerprint == subject_fingerprint
            )
        )
        connection.execute(
            delete(RateLimitGuard).where(
                RateLimitGuard.subject_fingerprint == subject_fingerprint
            )
        )
