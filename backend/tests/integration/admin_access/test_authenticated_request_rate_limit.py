"""T092 PostgreSQL evidence for per-account authenticated request limits."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.rate_limit import (
    AuthenticatedAdministrativeRequestLimitError,
    LimitAuthenticatedAdministrativeRequests,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.domain.authentication.rate_limit import (
    AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT,
)
from backend.app.infrastructure.persistence.admin_rate_limit_repository import (
    PostgresAdministrativeRateLimitStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import RateLimitEvent, RateLimitGuard
from backend.app.infrastructure.security.administrative_rate_limit_subject import (
    AdministrativeRateLimitSubjectProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_test_database_url,
)
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.request_rate_limit import (
    get_authenticated_administrative_request_limiter,
    _PostgresAuthenticatedAdministrativeRequestLimiter,
)
from backend.app.web.admin_auth.session_context import (
    get_administrative_session_context_loader,
    router as session_router,
)
from backend.app.application.admin_access.mutation_protection import (
    AdministrativeSessionAuthenticationError,
)
from backend.app.application.admin_access.session_context import (
    AdministrativeSessionContext,
)


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2030, 6, 1, 10, tzinfo=timezone.utc)
_KEY_RING = CryptographyKeyRing(load_cryptography_key_configuration())
_SUBJECTS = AdministrativeRateLimitSubjectProtector(key_ring=_KEY_RING)


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()


@pytest.mark.integration
def test_t092_postgres_enforces_120_requests_per_account_and_independent_budgets(
    migrated_engine: Engine,
) -> None:
    account_one = _SUBJECTS.fingerprint_account(8_200_001)
    account_two = _SUBJECTS.fingerprint_account(8_200_002)
    try:
        for index in range(120):
            assert _attempt(migrated_engine, account_one, NOW)
        assert not _attempt(migrated_engine, account_one, NOW)

        # Owner and staff roles have no shared/global subject: account identity
        # alone defines each independently revalidated actor's budget.
        for _ in range(120):
            assert _attempt(migrated_engine, account_two, NOW)
        assert not _attempt(migrated_engine, account_two, NOW)
        assert _event_count(migrated_engine, account_one) == 120
        assert _event_count(migrated_engine, account_two) == 120

        assert _attempt(migrated_engine, account_one, NOW + timedelta(minutes=1))
        assert _event_count(migrated_engine, account_one) == 121
    finally:
        _delete_subject(migrated_engine, account_one)
        _delete_subject(migrated_engine, account_two)


@pytest.mark.integration
def test_t092_postgres_serializes_121_concurrent_requests_to_exactly_120(
    migrated_engine: Engine,
) -> None:
    account_subject = _SUBJECTS.fingerprint_account(8_200_003)
    barrier = Barrier(21)

    def attempt(_: int) -> bool:
        barrier.wait(timeout=20)
        return _attempt(migrated_engine, account_subject, NOW)

    try:
        for _ in range(100):
            assert _attempt(migrated_engine, account_subject, NOW)
        with ThreadPoolExecutor(max_workers=21) as executor:
            outcomes = list(executor.map(attempt, range(21)))
        assert outcomes.count(True) == 20
        assert outcomes.count(False) == 1
        assert _event_count(migrated_engine, account_subject) == 120
    finally:
        _delete_subject(migrated_engine, account_subject)


@pytest.mark.integration
def test_t092_authenticated_429_is_sanitized_and_does_not_refresh_session(
    migrated_engine: Engine,
) -> None:
    account_id = 8_200_004
    subject = _SUBJECTS.fingerprint_account(account_id)
    session_loader = _AuthenticatedContextLoader(account_id=account_id)
    try:
        for _ in range(120):
            assert _attempt(migrated_engine, subject, datetime.now(timezone.utc))

        app = FastAPI()
        app.include_router(session_router)
        app.dependency_overrides[get_administrative_session_context_loader] = (
            lambda: session_loader
        )
        app.dependency_overrides[get_authenticated_administrative_request_limiter] = (
            lambda: _PostgresAuthenticatedAdministrativeRequestLimiter(
                engine=migrated_engine
            )
        )
        cookie = _encode(b"s" * 32)
        with TestClient(app) as client:
            response = client.get(
                "/api/admin/sessions/current",
                headers={
                    "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={cookie}",
                    "x-admin-account-id": "999999",
                    "x-admin-role": "staff",
                },
                params={"accountId": 999999, "role": "staff"},
            )

        assert response.status_code == 429
        assert response.json() == {
            "detail": "Demasiadas solicitudes. Inténtalo más tarde."
        }
        assert set(response.json()) == {"detail"}
        assert "set-cookie" not in response.headers
        assert cookie not in response.text
        assert session_loader.authenticated == [b"s" * 32]
        assert session_loader.refreshed == []
        assert session_loader.csrf_state == b"c" * 32
        assert _event_count(migrated_engine, subject) == 120
    finally:
        _delete_subject(migrated_engine, subject)


def _attempt(engine: Engine, subject: bytes, now: datetime) -> bool:
    try:
        with engine.begin() as connection:
            LimitAuthenticatedAdministrativeRequests(
                store=PostgresAdministrativeRateLimitStore(connection),
                clock=FixedClock(now),
                subject_fingerprint=subject,
                secret_generator=SystemSecretGenerator(),
            ).ensure_allowed()
    except AuthenticatedAdministrativeRequestLimitError:
        return False
    return True


def _event_count(engine: Engine, subject: bytes) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.category
                == AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
                RateLimitEvent.subject_fingerprint == subject,
            )
        ).scalar_one()


def _delete_subject(engine: Engine, subject: bytes) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(RateLimitEvent).where(
                RateLimitEvent.category
                == AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
                RateLimitEvent.subject_fingerprint == subject,
            )
        )
        connection.execute(
            delete(RateLimitGuard).where(
                RateLimitGuard.category
                == AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
                RateLimitGuard.subject_fingerprint == subject,
            )
        )


def _encode(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class _AuthenticatedContextLoader:
    def __init__(self, *, account_id: int) -> None:
        self.account_id = account_id
        self.authenticated = []
        self.refreshed = []
        self.csrf_state = b"c" * 32

    def authenticate(self, *, session_token: bytes | None) -> AdministrativeActor:
        self.authenticated.append(session_token)
        return AdministrativeActor(account_id=self.account_id, role="owner")

    def refresh(self, *, session_token: bytes | None) -> AdministrativeSessionContext:
        self.refreshed.append(session_token)
        self.csrf_state = b"d" * 32
        return AdministrativeSessionContext(
            actor=AdministrativeActor(account_id=self.account_id, role="owner"),
            csrf_token=self.csrf_state,
        )
