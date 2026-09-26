"""T072 authenticated HTTP contract for requesting an own-email reservation."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)
from backend.app.web.admin_auth.own_email_change import (
    get_own_email_change_operation,
    router,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor


class Operation:
    def __init__(self, outcome: str = "reserved") -> None:
        self.outcome = outcome
        self.calls = []

    def request(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.outcome


def _client(operation: Operation):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_administrative_mutation_protection] = lambda: None
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: AdministrativeActor(
        account_id=9, role="staff"
    )
    app.dependency_overrides[get_own_email_change_operation] = lambda: operation
    return TestClient(app)


def test_t072_http_uses_only_authenticated_identity_and_does_not_return_link_or_new_email():
    operation = Operation()
    response = _client(operation).post(
        "/api/admin/account/email-change",
        json={
            "newEmail": "synthetic.new@example.test",
            "currentPassword": "synthetic password",
            "totpCode": "123456",
            "accountId": 1,
        },
    )

    assert response.status_code == 202
    assert operation.calls[0]["account_id"] == 9
    assert response.json() == {
        "deliveryStatus": "accepted",
        "detail": "Revisa el correo nuevo para confirmar. El actual sigue activo.",
    }
    assert "synthetic.new@example.test" not in response.text
    assert "token" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_t072_http_returns_sanitized_credential_and_reservation_failures():
    credential_response = _client(Operation("invalid_credentials")).post(
        "/api/admin/account/email-change",
        json={
            "newEmail": "synthetic.new@example.test",
            "currentPassword": "synthetic password",
            "totpCode": "000000",
        },
    )
    conflict_response = _client(Operation("unavailable")).post(
        "/api/admin/account/email-change",
        json={
            "newEmail": "synthetic.other@example.test",
            "currentPassword": "synthetic password",
            "totpCode": "123456",
        },
    )

    assert credential_response.status_code == 400
    assert credential_response.json() == {
        "detail": "No fue posible comprobar las credenciales."
    }
    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "detail": "No fue posible reservar el correo solicitado."
    }


def test_t073_http_delivery_failure_does_not_claim_email_was_sent():
    response = _client(Operation("delivery_failed")).post(
        "/api/admin/account/email-change",
        json={
            "newEmail": "synthetic.new@example.test",
            "currentPassword": "synthetic password",
            "totpCode": "123456",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "deliveryStatus": "failed",
        "detail": "No se pudo enviar el enlace. Tu correo actual sigue activo. Inténtalo de nuevo.",
    }
