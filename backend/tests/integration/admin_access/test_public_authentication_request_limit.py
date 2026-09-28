"""T091 PostgreSQL evidence for the shared public IP request budget."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select

from backend.app.application.admin_access.rate_limit import (
    ReserveAdministrativeRateLimit,
)
from backend.app.application.admin_access.login_session import (
    AdministrativeLoginSessionOutcome,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.public_request_limit import (
    LimitPublicAuthenticationRequests,
    PublicRequestRateLimitError,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.domain.authentication.rate_limit import (
    AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT,
)
from backend.app.infrastructure.persistence.admin_rate_limit_repository import (
    PostgresAdministrativeRateLimitStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import RateLimitEvent, RateLimitGuard
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.public_request_subject import PublicRequestSubjectProtector
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_test_database_url,
)
from backend.app.web.admin_auth.login import get_administrative_login, router as login_router
from backend.app.web.admin_auth.lost_factor_replacement_request import (
    PostgresLostFactorReplacementRequestOperations,
    get_lost_factor_replacement_request_operations,
    router as lost_factor_router,
)
from backend.app.web.admin_auth.password_recovery_request import (
    get_password_recovery_operations,
    router as recovery_router,
)
from backend.app.web.public_availability import (
    get_public_availability_reader,
    router as availability_router,
)
from backend.app.web.public_request_protection import (
    get_public_authentication_request_limiter,
    get_public_read_request_limiter,
)
from backend.app.application.public_request_limit import AllowPublicRequests


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
SHARED_CATEGORIES = (
    "login",
    "password_recovery",
    "lost_factor_replacement",
    "availability",
)


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
def test_t091_twenty_public_auth_requests_share_one_ip_budget_and_expire_at_15_minutes(
    migrated_engine: Engine,
) -> None:
    subject = uuid4().hex.encode("ascii")
    other_subject = uuid4().hex.encode("ascii")
    try:
        for index in range(20):
            _limiter(migrated_engine, subject, NOW).ensure_allowed(
                SHARED_CATEGORIES[index % len(SHARED_CATEGORIES)]
            )

        with pytest.raises(PublicRequestRateLimitError):
            _limiter(migrated_engine, subject, NOW).ensure_allowed("login")

        for category in SHARED_CATEGORIES:
            _limiter(migrated_engine, other_subject, NOW).ensure_allowed(category)

        assert _event_count(migrated_engine, subject) == 20
        assert _event_count(migrated_engine, other_subject) == 4

        with pytest.raises(PublicRequestRateLimitError):
            _limiter(
                migrated_engine,
                subject,
                NOW + timedelta(minutes=15, microseconds=-1),
            ).ensure_allowed("availability")

        _limiter(
            migrated_engine,
            subject,
            NOW + timedelta(minutes=15),
        ).ensure_allowed("password_recovery")
        assert _event_count(migrated_engine, subject) == 21
    finally:
        _delete_subject(migrated_engine, subject)
        _delete_subject(migrated_engine, other_subject)


@pytest.mark.integration
def test_t091_lost_factor_route_budget_uses_the_same_postgresql_category(
    migrated_engine: Engine,
) -> None:
    subject = uuid4().hex.encode("ascii")
    try:
        with migrated_engine.begin() as connection:
            store = PostgresAdministrativeRateLimitStore(connection)
            limiter = LimitPublicAuthenticationRequests(
                store=store,
                clock=FixedClock(NOW),
                subject_fingerprint=subject,
                secret_generator=SystemSecretGenerator(),
            )
            for category in SHARED_CATEGORIES[:3]:
                limiter.ensure_allowed(category)

            # T069's existing lost-factor adapter reserves this same registered
            # category directly; it must share, not duplicate, the public budget.
            assert ReserveAdministrativeRateLimit(
                store=store,
                clock=FixedClock(NOW),
            ).reserve(
                category=AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT.category,
                subject_fingerprint=subject,
                request_fingerprint=uuid4().hex.encode("ascii"),
            )

        assert _event_count(migrated_engine, subject) == 4
        with pytest.raises(PublicRequestRateLimitError):
            for _ in range(16):
                _limiter(migrated_engine, subject, NOW).ensure_allowed("availability")
            _limiter(migrated_engine, subject, NOW).ensure_allowed("login")
    finally:
        _delete_subject(migrated_engine, subject)


@pytest.mark.integration
def test_t091_concurrent_requests_never_exceed_twenty_for_one_origin(
    migrated_engine: Engine,
) -> None:
    subject = uuid4().hex.encode("ascii")
    barrier = Barrier(21)

    def attempt(index: int) -> str:
        barrier.wait(timeout=15)
        try:
            _limiter(migrated_engine, subject, NOW).ensure_allowed(
                SHARED_CATEGORIES[index % len(SHARED_CATEGORIES)]
            )
        except PublicRequestRateLimitError:
            return "rejected"
        return "accepted"

    try:
        with ThreadPoolExecutor(max_workers=21) as executor:
            outcomes = list(executor.map(attempt, range(21)))

        assert outcomes.count("accepted") == 20
        assert outcomes.count("rejected") == 1
        assert _event_count(migrated_engine, subject) == 20
    finally:
        _delete_subject(migrated_engine, subject)


@pytest.mark.integration
def test_t091_http_security_and_availability_routes_share_one_origin_budget(
    migrated_engine: Engine,
) -> None:
    app = FastAPI()
    app.include_router(login_router)
    app.include_router(recovery_router)
    app.include_router(lost_factor_router)
    app.include_router(availability_router)
    login = _FakeLogin()
    availability = _FakeAvailability()
    origin = "192.0.2.55"
    request_time = datetime.now(BUSINESS_TIME_ZONE)
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    subject = PublicRequestSubjectProtector(key_ring=key_ring).fingerprint_ip(origin)
    recovery = _FakeRecovery(
        _PostgresAuthenticationLimiter(migrated_engine, subject, request_time)
    )
    other_origin = "192.0.2.56"
    other_subject = PublicRequestSubjectProtector(key_ring=key_ring).fingerprint_ip(
        other_origin
    )
    app.dependency_overrides[get_public_authentication_request_limiter] = lambda: (
        _PostgresAuthenticationLimiter(migrated_engine, subject, request_time)
    )
    app.dependency_overrides[get_administrative_login] = lambda: login
    app.dependency_overrides[get_password_recovery_operations] = lambda: recovery
    app.dependency_overrides[get_lost_factor_replacement_request_operations] = lambda: (
        PostgresLostFactorReplacementRequestOperations(engine=migrated_engine)
    )
    app.dependency_overrides[get_public_availability_reader] = lambda: availability
    app.dependency_overrides[get_public_read_request_limiter] = AllowPublicRequests

    try:
        with TestClient(app, client=(origin, 50000)) as client:
            for index in range(20):
                response = _request_shared_flow(
                    client,
                    SHARED_CATEGORIES[index % len(SHARED_CATEGORIES)],
                )
                assert response.status_code != 429
                assert _event_count(migrated_engine, subject) == index + 1

            assert login.calls == 5
            assert recovery.calls == 5
            assert _event_count(migrated_engine, subject) == 20
            blocked = client.post(
                "/api/admin/sessions",
                json={
                    "email": "synthetic.owner@example.test",
                    "password": "synthetic password",
                    "totpCode": "123456",
                },
            )

        assert login.calls == 5
        assert _event_count(migrated_engine, subject) == 20
        assert blocked.status_code == 429
        assert blocked.json() == {
            "detail": "Demasiadas solicitudes. Inténtalo más tarde."
        }
        assert "internal" not in blocked.text.lower()
        assert "set-cookie" not in blocked.headers
        assert login.calls == 5
        assert recovery.calls == 5
        assert _event_count(migrated_engine, subject) == 20

        app.dependency_overrides[get_public_authentication_request_limiter] = lambda: (
            _PostgresAuthenticationLimiter(migrated_engine, other_subject, request_time)
        )
        with TestClient(app, client=(other_origin, 50001)) as client:
            other_origin_response = client.post(
                "/api/admin/sessions",
                json={
                    "email": "synthetic.owner@example.test",
                    "password": "synthetic password",
                    "totpCode": "123456",
                },
            )

        assert other_origin_response.status_code == 401
        assert _event_count(migrated_engine, other_subject) == 1
    finally:
        _delete_subject(migrated_engine, subject)
        _delete_subject(migrated_engine, other_subject)


def _limiter(engine: Engine, subject: bytes, now: datetime):
    return _PostgresAuthenticationLimiter(engine, subject, now)


class _PostgresAuthenticationLimiter:
    """Commit one shared-budget reservation as a separate request would."""

    def __init__(self, engine: Engine, subject: bytes, now: datetime) -> None:
        self._engine = engine
        self._subject = subject
        self._now = now

    def ensure_allowed(self, category: str) -> None:
        with self._engine.begin() as connection:
            limiter = LimitPublicAuthenticationRequests(
                store=PostgresAdministrativeRateLimitStore(connection),
                clock=FixedClock(self._now),
                subject_fingerprint=self._subject,
                secret_generator=SystemSecretGenerator(),
            )
            limiter.ensure_allowed(category)


class _FakeLogin:
    def __init__(self) -> None:
        self.calls = 0

    def login(self, **_credentials) -> AdministrativeLoginSessionOutcome:
        self.calls += 1
        return AdministrativeLoginSessionOutcome(rejection="invalid_credentials")


class _FakeRecovery:
    def __init__(self, limiter: _PostgresAuthenticationLimiter) -> None:
        self.calls = 0
        self._limiter = limiter

    def request(self, **_values) -> None:
        # The real operation owns the coordinated IP/account reservation. Keep
        # the HTTP fake honest about the public-IP half of T091's contract.
        self._limiter.ensure_allowed("password_recovery")
        self.calls += 1


class _FakeAvailability:
    def get_active_service_duration(self, *_args):
        return 60

    def list_scheduled_intervals(self):
        return ()

    def list_applicable_blocks(self, *_args):
        return ()


def _request_shared_flow(client: TestClient, category: str):
    if category == "login":
        return client.post(
            "/api/admin/sessions",
            json={
                "email": "synthetic.owner@example.test",
                "password": "synthetic password",
                "totpCode": "123456",
            },
        )
    if category == "password_recovery":
        return client.post(
            "/api/admin/password-recovery",
            json={"email": "synthetic.owner@example.test"},
        )
    if category == "lost_factor_replacement":
        return client.post(
            "/api/admin/totp-replacement/request",
            json={
                # Keep this T091 contract independent of T093's per-account
                # budget; the route still reserves the shared public-IP slot.
                "email": "unknown.synthetic@example.test",
                "password": "synthetic password",
            },
        )
    return client.get(
        "/api/public/availability",
        params={
            "branch": "chiconcuac",
            "service": "Servicio ficticio",
            "date": "2030-06-15",
        },
    )


def _event_count(engine: Engine, subject: bytes) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.category
                == AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT.category,
                RateLimitEvent.subject_fingerprint == subject,
            )
        ).scalar_one()


def _delete_subject(engine: Engine, subject: bytes) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(RateLimitEvent).where(RateLimitEvent.subject_fingerprint == subject)
        )
        connection.execute(
            delete(RateLimitGuard).where(RateLimitGuard.subject_fingerprint == subject)
        )
