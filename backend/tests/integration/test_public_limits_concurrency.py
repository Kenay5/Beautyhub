"""T072A PostgreSQL concurrency evidence for every public protection window."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, select

from backend.app.application.clock import FixedClock
from backend.app.application.public_credential_failures import (
    PUBLIC_CREDENTIAL_BLOCK_RESULT,
    PUBLIC_CREDENTIAL_EVENT_CATEGORY,
    PUBLIC_CREDENTIAL_FAILURE_RESULT,
    EnsurePublicCredentialAccess,
    PublicCredentialBlockedError,
    RecordPublicCredentialFailure,
)
from backend.app.application.public_request_limit import (
    PUBLIC_APPOINTMENT_EVENT_CATEGORY,
    PUBLIC_READ_ACCEPTED_RESULT,
    PUBLIC_READ_EVENT_CATEGORY,
    LimitPublicAppointmentRequests,
    LimitPublicReadRequests,
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
NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)


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
def test_t072a_public_read_limit_is_atomic_at_60_and_exactly_60_seconds(
    migrated_engine: Engine,
) -> None:
    fingerprint = f"t072a-read:{uuid4().hex}".encode("ascii")
    try:
        with migrated_engine.begin() as connection:
            limiter = LimitPublicReadRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=FixedClock(NOW),
                subject_fingerprint=fingerprint,
            )
            for _ in range(59):
                limiter.ensure_allowed("service_catalog")

        outcomes = _run_concurrently(
            tuple(
                lambda: _attempt_public_read(migrated_engine, fingerprint)
                for _ in range(2)
            )
        )

        assert sorted(outcomes) == ["accepted", "rejected"]
        assert _event_window(migrated_engine, fingerprint, PUBLIC_READ_EVENT_CATEGORY) == (
            60,
            NOW + timedelta(seconds=60),
        )

        with migrated_engine.begin() as connection:
            before_boundary = LimitPublicReadRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=FixedClock(NOW + timedelta(seconds=60, microseconds=-1)),
                subject_fingerprint=fingerprint,
            )
            with pytest.raises(PublicRequestRateLimitError):
                before_boundary.ensure_allowed("availability")

        assert _event_window(migrated_engine, fingerprint, PUBLIC_READ_EVENT_CATEGORY) == (
            60,
            NOW + timedelta(seconds=60),
        )

        with migrated_engine.begin() as connection:
            at_boundary = LimitPublicReadRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=FixedClock(NOW + timedelta(seconds=60)),
                subject_fingerprint=fingerprint,
            )
            at_boundary.ensure_allowed("availability")

        assert _event_count(migrated_engine, fingerprint, PUBLIC_READ_EVENT_CATEGORY) == 61
    finally:
        _delete_events(migrated_engine, fingerprint)


@pytest.mark.integration
def test_t072a_public_appointment_limit_is_atomic_at_10_and_exactly_15_minutes(
    migrated_engine: Engine,
) -> None:
    fingerprint = f"t072a-appointment:{uuid4().hex}".encode("ascii")
    try:
        with migrated_engine.begin() as connection:
            limiter = LimitPublicAppointmentRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=FixedClock(NOW),
                subject_fingerprint=fingerprint,
            )
            for _ in range(9):
                limiter.ensure_allowed("appointment_lookup")

        outcomes = _run_concurrently(
            tuple(
                lambda: _attempt_public_appointment_operation(
                    migrated_engine,
                    fingerprint,
                )
                for _ in range(2)
            )
        )

        assert sorted(outcomes) == ["accepted", "rejected"]
        assert _event_window(
            migrated_engine,
            fingerprint,
            PUBLIC_APPOINTMENT_EVENT_CATEGORY,
        ) == (10, NOW + timedelta(minutes=15))

        with migrated_engine.begin() as connection:
            before_boundary = LimitPublicAppointmentRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=FixedClock(NOW + timedelta(minutes=15, microseconds=-1)),
                subject_fingerprint=fingerprint,
            )
            with pytest.raises(PublicRequestRateLimitError):
                before_boundary.ensure_allowed("appointment_cancellation")

        assert _event_window(
            migrated_engine,
            fingerprint,
            PUBLIC_APPOINTMENT_EVENT_CATEGORY,
        ) == (10, NOW + timedelta(minutes=15))

        with migrated_engine.begin() as connection:
            at_boundary = LimitPublicAppointmentRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=FixedClock(NOW + timedelta(minutes=15)),
                subject_fingerprint=fingerprint,
            )
            at_boundary.ensure_allowed("appointment_modification")

        assert _event_count(
            migrated_engine,
            fingerprint,
            PUBLIC_APPOINTMENT_EVENT_CATEGORY,
        ) == 11
    finally:
        _delete_events(migrated_engine, fingerprint)


@pytest.mark.integration
def test_t072a_fifth_credential_failure_creates_one_nonextending_15_minute_block(
    migrated_engine: Engine,
) -> None:
    fingerprint = f"t072a-credential:{uuid4().hex}".encode("ascii")
    try:
        with migrated_engine.begin() as connection:
            recorder = RecordPublicCredentialFailure(
                store=PostgresPublicCredentialFailureStore(connection),
                clock=FixedClock(NOW),
            )
            for _ in range(4):
                recorder.record_failure(subject_fingerprint=fingerprint)

        outcomes = _run_concurrently(
            tuple(
                lambda: _attempt_public_credential_failure(
                    migrated_engine,
                    fingerprint,
                )
                for _ in range(2)
            )
        )

        assert sorted(outcomes) == ["blocked", "created"]
        assert _credential_window(migrated_engine, fingerprint) == (
            5,
            1,
            NOW + timedelta(minutes=15),
        )

        with migrated_engine.begin() as connection:
            store = PostgresPublicCredentialFailureStore(connection)
            before_boundary = FixedClock(
                NOW + timedelta(minutes=15, microseconds=-1)
            )
            with pytest.raises(PublicCredentialBlockedError):
                EnsurePublicCredentialAccess(
                    store=store,
                    clock=before_boundary,
                ).ensure_allowed(subject_fingerprint=fingerprint)
            with pytest.raises(PublicCredentialBlockedError):
                RecordPublicCredentialFailure(
                    store=store,
                    clock=before_boundary,
                ).record_failure(subject_fingerprint=fingerprint)

        assert _credential_window(migrated_engine, fingerprint) == (
            5,
            1,
            NOW + timedelta(minutes=15),
        )

        with migrated_engine.begin() as connection:
            store = PostgresPublicCredentialFailureStore(connection)
            at_boundary = FixedClock(NOW + timedelta(minutes=15))
            EnsurePublicCredentialAccess(
                store=store,
                clock=at_boundary,
            ).ensure_allowed(subject_fingerprint=fingerprint)
            result = RecordPublicCredentialFailure(
                store=store,
                clock=at_boundary,
            ).record_failure(subject_fingerprint=fingerprint)

        assert result.failure_count == 1
        assert result.block_expires_at is None
        assert _event_count(
            migrated_engine,
            fingerprint,
            PUBLIC_CREDENTIAL_EVENT_CATEGORY,
        ) == 7
    finally:
        _delete_events(migrated_engine, fingerprint)


def _run_concurrently(workers: tuple[Callable[[], str], ...]) -> list[str]:
    barrier = Barrier(len(workers))

    def synchronized(worker: Callable[[], str]) -> str:
        barrier.wait(timeout=10)
        return worker()

    with ThreadPoolExecutor(max_workers=len(workers)) as executor:
        return list(executor.map(synchronized, workers))


def _attempt_public_read(engine: Engine, fingerprint: bytes) -> str:
    with engine.begin() as connection:
        limiter = LimitPublicReadRequests(
            store=PostgresPublicRequestWindowStore(connection),
            clock=FixedClock(NOW),
            subject_fingerprint=fingerprint,
        )
        try:
            limiter.ensure_allowed("availability")
        except PublicRequestRateLimitError:
            return "rejected"
    return "accepted"


def _attempt_public_appointment_operation(
    engine: Engine,
    fingerprint: bytes,
) -> str:
    with engine.begin() as connection:
        limiter = LimitPublicAppointmentRequests(
            store=PostgresPublicRequestWindowStore(connection),
            clock=FixedClock(NOW),
            subject_fingerprint=fingerprint,
        )
        try:
            limiter.ensure_allowed("appointment_confirmation")
        except PublicRequestRateLimitError:
            return "rejected"
    return "accepted"


def _attempt_public_credential_failure(engine: Engine, fingerprint: bytes) -> str:
    with engine.begin() as connection:
        recorder = RecordPublicCredentialFailure(
            store=PostgresPublicCredentialFailureStore(connection),
            clock=FixedClock(NOW),
        )
        try:
            result = recorder.record_failure(subject_fingerprint=fingerprint)
        except PublicCredentialBlockedError:
            return "blocked"
    assert result.block_expires_at == NOW + timedelta(minutes=15)
    return "created"


def _event_window(
    engine: Engine,
    fingerprint: bytes,
    category: str,
) -> tuple[int, datetime | None]:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count(), func.max(PublicRequestEvent.expires_at)).where(
                PublicRequestEvent.subject_fingerprint == fingerprint,
                PublicRequestEvent.category == category,
                PublicRequestEvent.result == PUBLIC_READ_ACCEPTED_RESULT,
            )
        ).one()


def _event_count(engine: Engine, fingerprint: bytes, category: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(PublicRequestEvent)
            .where(
                PublicRequestEvent.subject_fingerprint == fingerprint,
                PublicRequestEvent.category == category,
            )
        ).scalar_one()


def _credential_window(
    engine: Engine,
    fingerprint: bytes,
) -> tuple[int, int, datetime | None]:
    with engine.connect() as connection:
        failure_count, block_count, latest_expiry = connection.execute(
            select(
                func.count().filter(
                    PublicRequestEvent.result == PUBLIC_CREDENTIAL_FAILURE_RESULT
                ),
                func.count().filter(
                    PublicRequestEvent.result == PUBLIC_CREDENTIAL_BLOCK_RESULT
                ),
                func.max(PublicRequestEvent.expires_at),
            ).where(
                PublicRequestEvent.subject_fingerprint == fingerprint,
                PublicRequestEvent.category == PUBLIC_CREDENTIAL_EVENT_CATEGORY,
            )
        ).one()
    return failure_count, block_count, latest_expiry


def _delete_events(engine: Engine, fingerprint: bytes) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(PublicRequestEvent).where(
                PublicRequestEvent.subject_fingerprint == fingerprint
            )
        )
