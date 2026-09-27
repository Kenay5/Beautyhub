"""HTTP permissions and minimal-response contract for administrative history."""

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.application.admin_access.administrative_history import (
    AdministrativeHistoryEntry,
    AdministrativeHistoryFilters,
)
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.web.admin_auth.administrative_history import (
    get_administrative_history_operations,
    router,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor


NOW = datetime(2026, 9, 26, 16, tzinfo=timezone.utc)
ENTRY = AdministrativeHistoryEntry(
    event_id=13,
    actor_account_id=7,
    action="appointment_modified",
    result="succeeded",
    occurred_at=NOW,
    target_reference="appointment:21",
)


class Operations:
    def __init__(self) -> None:
        self.reads: list[tuple[str, object]] = []
        self.denials: list[tuple[int, str, str]] = []

    def list_events(self, *, actor, filters: AdministrativeHistoryFilters):
        if actor.role != "owner":
            self.denials.append((actor.account_id, "authorization_denied", "denied"))
            raise AdministrativeAuthorizationError("forbidden")
        self.reads.append(("list", filters))
        return (ENTRY,), (7,)

    def get_event(self, *, actor, event_id: int):
        if actor.role != "owner":
            self.denials.append((actor.account_id, "authorization_denied", "denied"))
            raise AdministrativeAuthorizationError("forbidden")
        self.reads.append(("detail", event_id))
        return ENTRY if event_id == ENTRY.event_id else None


def _client(actor, operations: Operations) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_administrative_history_operations] = lambda: operations
    if actor is not _UNAUTHENTICATED:
        app.dependency_overrides[get_authenticated_admin_actor] = lambda: actor
    else:
        app.dependency_overrides[get_authenticated_admin_actor] = _raise_unauthenticated
    return TestClient(app)


_UNAUTHENTICATED = object()


def _raise_unauthenticated():
    raise HTTPException(
        status_code=401, detail="Autenticación administrativa requerida."
    )


def test_t086_history_http_returns_only_minimum_fields_to_owner() -> None:
    operations = Operations()
    owner = AdministrativeActor(account_id=1, role="owner")

    with _client(owner, operations) as client:
        response = client.get(
            "/api/admin/history",
            params={"accountId": 7, "action": "appointment_modified", "fromDate": "2026-09-26", "toDate": "2026-09-26"},
        )
        detail = client.get("/api/admin/history/13")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "events": [
            {
                "eventId": 13,
                "actorAccountId": 7,
                "action": "appointment_modified",
                "result": "succeeded",
                "occurredAt": NOW.isoformat().replace("+00:00", "Z"),
                "targetReference": "appointment:21",
            }
        ],
        "accountIds": [7],
    }
    assert detail.status_code == 200
    assert detail.json() == response.json()["events"][0]
    assert operations.denials == []
    assert [read[0] for read in operations.reads] == ["list", "detail"]


def test_t086_missing_session_cannot_list_or_read_individual_event() -> None:
    operations = Operations()

    with _client(_UNAUTHENTICATED, operations) as client:
        listing = client.get("/api/admin/history")
        detail = client.get("/api/admin/history/13")

    assert listing.status_code == 401
    assert detail.status_code == 401
    assert operations.reads == []
    assert operations.denials == []


def test_t086_staff_cannot_manually_list_or_read_event() -> None:
    operations = Operations()
    staff = AdministrativeActor(account_id=8, role="staff")

    with _client(staff, operations) as client:
        listing = client.get("/api/admin/history", headers={"x-admin-role": "owner"})
        detail = client.get(
            "/api/admin/history/13",
            headers={"x-admin-account-id": "1", "x-admin-role": "owner"},
        )

    assert listing.status_code == 403
    assert detail.status_code == 403
    assert listing.json() == {
        "detail": "No tienes permiso para consultar el historial administrativo."
    }
    assert operations.reads == []
    assert operations.denials == [
        (8, "authorization_denied", "denied"),
        (8, "authorization_denied", "denied"),
    ]


def test_t086_invalid_filters_are_rejected_without_reading() -> None:
    operations = Operations()
    owner = AdministrativeActor(account_id=1, role="owner")

    with _client(owner, operations) as client:
        response = client.get(
            "/api/admin/history", params={"fromDate": "2026-09-27", "toDate": "2026-09-26"}
        )

    assert response.status_code == 422
    assert operations.reads == []
    assert operations.denials == []
