"""T093 PostgreSQL evidence for shared manual security-message budgets."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.staff_invitation import StaffInvitationDeliveryOutcome
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.domain.authentication.rate_limit import (
    AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT,
    SECURITY_MESSAGE_ACTION_LIMIT,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import RateLimitEvent, RateLimitGuard
from backend.app.infrastructure.persistence.security_message_rate_limit_repository import (
    PostgresSecurityMessageActionBudget,
)
from backend.app.infrastructure.security.administrative_rate_limit_subject import (
    AdministrativeRateLimitSubjectProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_test_database_url,
)
from backend.app.web.admin_auth.forced_staff_password_reset import (
    ForcedPasswordResetResponse,
    get_forced_password_reset_operations,
    router as forced_reset_router,
)
from backend.app.web.admin_auth.change_password import (
    get_password_change_operation,
    router as password_change_router,
)
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)
from backend.app.web.admin_auth.own_email_change import (
    get_own_email_change_operation,
    router as own_email_router,
)
from backend.app.web.admin_auth.security_message_rate_limit import (
    _PostgresSecurityMessageActionLimiter,
    get_security_message_action_limiter,
)
from backend.app.web.admin_auth.request_rate_limit import (
    _PostgresAuthenticatedAdministrativeRequestLimiter,
    get_authenticated_administrative_request_limiter,
)
from backend.app.web.admin_auth.session_context import get_revalidated_admin_actor
from backend.app.web.admin_auth.staff_invitations import (
    get_staff_invitation_operations,
    router as staff_invitation_router,
)


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2030, 6, 1, 10, tzinfo=timezone.utc)
_SUBJECTS = AdministrativeRateLimitSubjectProtector(
    key_ring=CryptographyKeyRing(load_cryptography_key_configuration())
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
def test_t093_ten_manual_message_actions_share_one_account_budget_and_expire(
    migrated_engine: Engine,
) -> None:
    account_id = 8_300_001
    subject = _SUBJECTS.fingerprint_account(account_id)
    try:
        # Different manually initiated flows use the same category and subject.
        for manual_flow in (
            "password_recovery",
            "lost_factor_replacement",
            "staff_invitation",
            "forced_password_reset",
            "own_email_change",
        ):
            for _ in range(2):
                assert _reserve(migrated_engine, account_id, NOW)
        assert not _reserve(migrated_engine, account_id, NOW)

        assert _event_count(migrated_engine, subject) == 10
        assert _reserve(migrated_engine, account_id, NOW + timedelta(minutes=15))
        assert _event_count(migrated_engine, subject) == 11
    finally:
        _delete_subject(migrated_engine, subject)


@pytest.mark.integration
def test_t093_distinct_administrative_accounts_have_independent_budgets(
    migrated_engine: Engine,
) -> None:
    owner_subject = _SUBJECTS.fingerprint_account(8_300_002)
    staff_subject = _SUBJECTS.fingerprint_account(8_300_003)
    try:
        for _ in range(10):
            assert _reserve(migrated_engine, 8_300_002, NOW)
        assert not _reserve(migrated_engine, 8_300_002, NOW)
        for _ in range(10):
            assert _reserve(migrated_engine, 8_300_003, NOW)
        assert not _reserve(migrated_engine, 8_300_003, NOW)
        assert _event_count(migrated_engine, owner_subject) == 10
        assert _event_count(migrated_engine, staff_subject) == 10
    finally:
        _delete_subject(migrated_engine, owner_subject)
        _delete_subject(migrated_engine, staff_subject)


@pytest.mark.integration
def test_t093_postgres_serializes_the_tenth_manual_message_reservation(
    migrated_engine: Engine,
) -> None:
    account_id = 8_300_004
    subject = _SUBJECTS.fingerprint_account(account_id)
    barrier = Barrier(12)

    def attempt(_: int) -> bool:
        barrier.wait(timeout=20)
        return _reserve(migrated_engine, account_id, NOW)

    try:
        for _ in range(8):
            assert _reserve(migrated_engine, account_id, NOW)
        with ThreadPoolExecutor(max_workers=12) as executor:
            outcomes = list(executor.map(attempt, range(12)))
        assert outcomes.count(True) == 2
        assert outcomes.count(False) == 10
        assert _event_count(migrated_engine, subject) == 10
    finally:
        _delete_subject(migrated_engine, subject)


@pytest.mark.integration
def test_t093_authenticated_manual_flows_share_budget_and_429_precedes_effects(
    migrated_engine: Engine,
) -> None:
    actor = AdministrativeActor(account_id=8_300_005, role="owner")
    subject = _SUBJECTS.fingerprint_account(actor.account_id)
    calls = {
        "invitation": 0,
        "reset": 0,
        "email_change": 0,
        "automatic_notice_action": 0,
        "protection": 0,
    }

    class Operations:
        def invite(self, *, actor, email):
            calls["invitation"] += 1
            return StaffInvitationDeliveryOutcome(accepted=True)

        def resend(self, *, actor):
            calls["invitation"] += 1
            return StaffInvitationDeliveryOutcome(accepted=True)

        def cancel(self, *, actor):
            raise AssertionError("cancellation does not send a security message")

        def force(self, *, actor):
            calls["reset"] += 1
            return ForcedPasswordResetResponse(delivery_status="accepted")

        def request(self, **_values):
            calls["email_change"] += 1
            return "reserved"

        def change(self, **_values):
            calls["automatic_notice_action"] += 1
            return "changed"

    operations = Operations()
    app = FastAPI()
    app.include_router(staff_invitation_router)
    app.include_router(forced_reset_router)
    app.include_router(own_email_router)
    app.include_router(password_change_router)
    app.dependency_overrides[get_revalidated_admin_actor] = lambda: actor
    app.dependency_overrides[get_security_message_action_limiter] = lambda: (
        _PostgresSecurityMessageActionLimiter(engine=migrated_engine)
    )
    app.dependency_overrides[get_authenticated_administrative_request_limiter] = (
        lambda: _PostgresAuthenticatedAdministrativeRequestLimiter(
            engine=migrated_engine
        )
    )

    def protection():
        calls["protection"] += 1

    app.dependency_overrides[require_administrative_mutation_protection] = protection
    app.dependency_overrides[get_staff_invitation_operations] = lambda: operations
    app.dependency_overrides[get_forced_password_reset_operations] = (
        lambda: operations
    )
    app.dependency_overrides[get_own_email_change_operation] = lambda: operations
    app.dependency_overrides[get_password_change_operation] = lambda: operations
    routes = (
        lambda client: client.post(
            "/api/admin/staff-invitations",
            json={"email": "synthetic.staff@example.test"},
        ),
        lambda client: client.post("/api/admin/staff-password-reset"),
        lambda client: client.post(
            "/api/admin/account/email-change",
            json={
                "newEmail": "synthetic.new@example.test",
                "currentPassword": "synthetic password",
                "totpCode": "123456",
            },
        ),
    )
    try:
        with TestClient(app) as client:
            responses = [routes[index % len(routes)](client) for index in range(10)]
            denied = client.post("/api/admin/staff-password-reset")
            calls_after_denial = calls.copy()
            automatic_notice = client.post(
                "/api/admin/password",
                json={
                    "currentPassword": "synthetic old password",
                    "totpCode": "123456",
                    "newPassword": "synthetic new password phrase",
                },
            )

        assert all(response.status_code in {201, 200, 202} for response in responses)
        assert denied.status_code == 429
        assert denied.json() == {
            "detail": "Demasiadas solicitudes. Inténtalo más tarde."
        }
        assert set(denied.json()) == {"detail"}
        assert "set-cookie" not in denied.headers
        assert calls_after_denial == {
            "invitation": 4,
            "reset": 3,
            "email_change": 3,
            "automatic_notice_action": 0,
            "protection": 10,
        }
        assert _event_count(migrated_engine, subject) == 10
        assert automatic_notice.status_code == 204
        assert _event_count(migrated_engine, subject) == 10
        assert calls["automatic_notice_action"] == 1
        assert calls["protection"] == 11
    finally:
        _delete_subject(migrated_engine, subject)


def _reserve(engine: Engine, account_id: int, now: datetime) -> bool:
    with engine.begin() as connection:
        return PostgresSecurityMessageActionBudget(
            connection=connection,
            subject_protector=_SUBJECTS,
            clock=FixedClock(now),
            secret_generator=SystemSecretGenerator(),
        ).reserve(account_id=account_id)


def _event_count(engine: Engine, subject: bytes) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.category == SECURITY_MESSAGE_ACTION_LIMIT.category,
                RateLimitEvent.subject_fingerprint == subject,
            )
        ).scalar_one()


def _delete_subject(engine: Engine, subject: bytes) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(RateLimitEvent).where(
                RateLimitEvent.category.in_(
                    (
                        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
                        SECURITY_MESSAGE_ACTION_LIMIT.category,
                    )
                ),
                RateLimitEvent.subject_fingerprint == subject,
            )
        )
        connection.execute(
            delete(RateLimitGuard).where(
                RateLimitGuard.category.in_(
                    (
                        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
                        SECURITY_MESSAGE_ACTION_LIMIT.category,
                    )
                ),
                RateLimitGuard.subject_fingerprint == subject,
            )
        )
