"""PostgreSQL evidence for T086 history filtering and authorization side effects."""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.clock import FixedClock
from backend.app.domain.audit.history_period import ADMINISTRATIVE_HISTORY_TIMEZONE
from backend.app.web.admin_auth.administrative_history import (
    PostgresAdministrativeHistoryOperations,
    get_administrative_history_operations,
    router,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.tests.integration.admin_access.test_admin_login_session import (
    migrated_engine,
)


NOW = datetime(2026, 9, 26, 16, tzinfo=timezone.utc)


@pytest.fixture
def history_engine(migrated_engine):
    return migrated_engine


def _seed_events(engine) -> tuple[int, int, date, list[int]]:
    local_day = NOW.astimezone(ADMINISTRATIVE_HISTORY_TIMEZONE).date()
    local_start = datetime.combine(local_day, time.min, ADMINISTRATIVE_HISTORY_TIMEZONE)
    local_end = datetime.combine(
        local_day + timedelta(days=1), time.min, ADMINISTRATIVE_HISTORY_TIMEZONE
    )
    expired = datetime.combine(
        local_day - timedelta(days=365), time(hour=10), ADMINISTRATIVE_HISTORY_TIMEZONE
    ).astimezone(timezone.utc)
    timestamps = [
        local_start.astimezone(timezone.utc),
        (local_end - timedelta(microseconds=1)).astimezone(timezone.utc),
        local_end.astimezone(timezone.utc),
        datetime.combine(local_day, time(hour=12), ADMINISTRATIVE_HISTORY_TIMEZONE).astimezone(timezone.utc),
        expired,
    ]
    with engine.begin() as connection:
        owner_id = connection.execute(
            text(
                "INSERT INTO admin_accounts (role, status) "
                "VALUES ('owner', 'inactive') RETURNING admin_account_id"
            )
        ).scalar_one()
        staff_id = connection.execute(
            text(
                "INSERT INTO admin_accounts (role, status) "
                "VALUES ('staff', 'deactivated') RETURNING admin_account_id"
            )
        ).scalar_one()
        event_ids = []
        values = (
            (owner_id, "login", "succeeded", timestamps[0], None),
            (owner_id, "login", "failed", timestamps[1], None),
            (owner_id, "login", "succeeded", timestamps[2], None),
            (staff_id, "password_change", "succeeded", timestamps[3], None),
            (owner_id, "logout", "succeeded", timestamps[4], None),
        )
        for actor_id, action, result, occurred_at, target in values:
            event_ids.append(
                connection.execute(
                    text(
                        "INSERT INTO admin_audit_events (actor_account_id, action, "
                        "result, occurred_at, target_reference) VALUES "
                        "(:actor_id, :action, :result, :occurred_at, :target) "
                        "RETURNING admin_audit_event_id"
                    ),
                    {
                        "actor_id": actor_id,
                        "action": action,
                        "result": result,
                        "occurred_at": occurred_at,
                        "target": target,
                    },
                ).scalar_one()
            )
    return owner_id, staff_id, local_day, event_ids


def _client(engine, actor):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_administrative_history_operations] = lambda: PostgresAdministrativeHistoryOperations(
        engine=engine, clock=FixedClock(NOW)
    )
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: actor
    return TestClient(app)


def _audit_count(engine) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM admin_audit_events")
        ).scalar_one()


@pytest.mark.integration
def test_t086_owner_filters_by_actor_action_and_official_local_period(
    history_engine,
) -> None:
    owner_id, staff_id, local_day, event_ids = _seed_events(history_engine)
    before = _audit_count(history_engine)

    with _client(history_engine, AdministrativeActor(account_id=owner_id, role="owner")) as client:
        unfiltered = client.get("/api/admin/history")
        response = client.get(
            "/api/admin/history",
            params={
                "accountId": owner_id,
                "action": "login",
                "fromDate": local_day.isoformat(),
                "toDate": local_day.isoformat(),
            },
        )
        detail = client.get(f"/api/admin/history/{event_ids[0]}")
        expired_detail = client.get(f"/api/admin/history/{event_ids[-1]}")

    assert response.status_code == 200
    assert unfiltered.status_code == 200
    assert event_ids[-1] not in {
        event["eventId"] for event in unfiltered.json()["events"]
    }
    payload = response.json()
    assert [event["eventId"] for event in payload["events"]] == list(
        reversed(event_ids[:2])
    )
    assert payload["accountIds"] == [owner_id, staff_id]
    assert {event["action"] for event in payload["events"]} == {"login"}
    assert all(event["actorAccountId"] == owner_id for event in payload["events"])
    assert detail.status_code == 200
    assert detail.json()["eventId"] == event_ids[0]
    assert expired_detail.status_code == 404
    assert "email" not in str(payload).lower()
    assert "password" not in str(payload).lower()
    assert "ip" not in str(payload).lower()
    assert _audit_count(history_engine) == before


@pytest.mark.integration
def test_t086_staff_cannot_list_or_read_events_and_only_denial_is_recorded(
    history_engine,
) -> None:
    _owner_id, staff_id, _local_day, _event_ids = _seed_events(history_engine)
    before = _audit_count(history_engine)

    with _client(history_engine, AdministrativeActor(account_id=staff_id, role="staff")) as client:
        listing = client.get("/api/admin/history", headers={"x-admin-role": "owner"})
        detail = client.get("/api/admin/history/1", headers={"x-admin-account-id": "1"})

    assert listing.status_code == detail.status_code == 403
    assert _audit_count(history_engine) == before + 2
    with history_engine.connect() as connection:
        denials = connection.execute(
            text(
                "SELECT actor_account_id, action, result, target_reference "
                "FROM admin_audit_events WHERE actor_account_id = :staff_id "
                "AND action = 'authorization_denied' ORDER BY admin_audit_event_id DESC LIMIT 2"
            ),
            {"staff_id": staff_id},
        ).all()
    assert denials == [
        (staff_id, "authorization_denied", "denied", None),
        (staff_id, "authorization_denied", "denied", None),
    ]
