"""HTTP evidence for the T035-T037 staff invitation adapters."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.staff_invitation import StaffInvitationDeliveryOutcome
from backend.app.web.admin_auth.staff_invitations import (
    get_authenticated_admin_actor,
    get_staff_invitation_operations,
    router,
)
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)


class RecordingOperations:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[tuple[str, object]] = []

    def invite(self, *, actor, email):
        self.calls.append(("invite", (actor, email)))
        return StaffInvitationDeliveryOutcome(
            accepted=self.accepted,
            detail=None if self.accepted else "No se pudo enviar el correo. Inténtalo de nuevo.",
        )

    def resend(self, *, actor):
        self.calls.append(("resend", actor))
        return StaffInvitationDeliveryOutcome(accepted=self.accepted)

    def cancel(self, *, actor):
        self.calls.append(("cancel", actor))


def _client(operations: RecordingOperations, *, actor: AdministrativeActor | None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_staff_invitation_operations] = lambda: operations
    app.dependency_overrides[require_administrative_mutation_protection] = lambda: None
    if actor is not None:
        app.dependency_overrides[get_authenticated_admin_actor] = lambda: actor
    return TestClient(app)


def test_t035_invitation_is_closed_without_server_authenticated_identity() -> None:
    operations = RecordingOperations()
    with _client(operations, actor=None) as client:
        response = client.post(
            "/api/admin/staff-invitations",
            json={"email": "synthetic.staff@example.test"},
        )

    assert response.status_code == 401
    assert operations.calls == []


def test_t035_owner_can_create_pending_invitation_without_secret_fields() -> None:
    operations = RecordingOperations()
    owner = AdministrativeActor(account_id=7, role="owner")
    with _client(operations, actor=owner) as client:
        response = client.post(
            "/api/admin/staff-invitations",
            json={"email": "synthetic.staff@example.test"},
        )

    assert response.status_code == 201
    assert response.json() == {
        "status": "pending",
        "deliveryStatus": "accepted",
        "detail": None,
    }
    assert operations.calls == [("invite", (owner, "synthetic.staff@example.test"))]
    assert "token" not in response.text.lower()


def test_t036_delivery_failure_is_sanitized_and_remains_manageable() -> None:
    operations = RecordingOperations(accepted=False)
    owner = AdministrativeActor(account_id=7, role="owner")
    with _client(operations, actor=owner) as client:
        response = client.post(
            "/api/admin/staff-invitations",
            json={"email": "synthetic.staff@example.test"},
        )

    assert response.status_code == 201
    assert response.json() == {
        "status": "pending",
        "deliveryStatus": "failed",
        "detail": "No se pudo enviar el correo. Inténtalo de nuevo.",
    }


def test_t037_owner_can_resend_and_cancel_the_pending_invitation() -> None:
    operations = RecordingOperations()
    owner = AdministrativeActor(account_id=7, role="owner")
    with _client(operations, actor=owner) as client:
        resent = client.post("/api/admin/staff-invitations/resend")
        cancelled = client.post("/api/admin/staff-invitations/cancel")

    assert resent.status_code == 200
    assert cancelled.status_code == 204
    assert operations.calls == [("resend", owner), ("cancel", owner)]
