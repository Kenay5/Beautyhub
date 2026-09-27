from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.web.admin_auth.mutation_protection import require_administrative_mutation_protection
from backend.app.web.admin_auth.staff_deactivation import (
    get_authenticated_admin_actor,
    get_staff_deactivation_operations,
    router,
)


class Operations:
    def __init__(self):
        self.calls = []
        self.business_changes = 0
        self.audit_events = []

    def status(self, *, actor):
        self.calls.append(("status", actor))
        return "active"

    def deactivate(self, *, actor):
        self.calls.append(("deactivate", actor))
        if actor.role != "owner":
            self.audit_events.append({
                "actor_account_id": actor.account_id,
                "action": "authorization_denied",
                "result": "denied",
            })
            raise AdministrativeAuthorizationError("forbidden")
        self.business_changes += 1


def _client(operations, actor):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_staff_deactivation_operations] = lambda: operations
    app.dependency_overrides[require_administrative_mutation_protection] = lambda: None
    if actor is not None:
        app.dependency_overrides[get_authenticated_admin_actor] = lambda: actor
    return TestClient(app)


def _invalid_session():
    raise HTTPException(
        status_code=401,
        detail="Autenticación administrativa requerida.",
    )


def test_t080_deactivation_requires_authenticated_actor():
    operations = Operations()
    with _client(operations, None) as client:
        response = client.post("/api/admin/staff/deactivate")
    assert response.status_code == 401
    assert operations.calls == []
    assert operations.audit_events == []


def test_t083_invalid_session_cannot_reach_mutation_or_create_denial_audit():
    operations = Operations()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_staff_deactivation_operations] = lambda: operations
    app.dependency_overrides[require_administrative_mutation_protection] = lambda: None
    app.dependency_overrides[get_authenticated_admin_actor] = _invalid_session

    with TestClient(app) as client:
        response = client.post(
            "/api/admin/staff/deactivate",
            headers={"cookie": "beautyhub_admin_session=invalid"},
        )

    assert response.status_code == 401
    assert operations.calls == []
    assert operations.business_changes == 0
    assert operations.audit_events == []


def test_t080_staff_cannot_deactivate_self_or_another_account():
    operations = Operations()
    staff = AdministrativeActor(account_id=8, role="staff")
    with _client(operations, staff) as client:
        response = client.post(
            "/api/admin/staff/deactivate",
            json={"accountId": 1, "role": "owner", "identity": 1},
            headers={"x-admin-role": "owner", "x-admin-account-id": "1"},
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "No tienes permiso para realizar esta operación."}
    assert operations.calls == [("deactivate", staff)]
    assert operations.business_changes == 0
    assert operations.audit_events == [{
        "actor_account_id": 8,
        "action": "authorization_denied",
        "result": "denied",
    }]


def test_t080_owner_can_deactivate_without_client_selected_target():
    operations = Operations()
    owner = AdministrativeActor(account_id=1, role="owner")
    with _client(operations, owner) as client:
        response = client.post("/api/admin/staff/deactivate", json={"accountId": 1})
    assert response.status_code == 204
    assert operations.calls == [("deactivate", owner)]
    assert operations.business_changes == 1


def test_t080_owner_status_is_minimal_and_server_authorized():
    operations = Operations()
    owner = AdministrativeActor(account_id=1, role="owner")
    with _client(operations, owner) as client:
        response = client.get("/api/admin/staff/current")
    assert response.status_code == 200
    assert response.json() == {"status": "active"}
    assert operations.calls == [("status", owner)]
