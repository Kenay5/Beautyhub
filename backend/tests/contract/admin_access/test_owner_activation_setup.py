"""T033 HTTP contract evidence for unconfirmed owner activation setup."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.owner_activation_setup import (
    OwnerActivationSetupError,
    PreparedOwnerActivationSetup,
)
from backend.app.application.admin_access.owner_activation import OwnerActivationOutcome
from backend.app.web.admin_auth.owner_activation_setup import (
    get_owner_activation_abandoner,
    get_owner_activation_completer,
    get_owner_activation_preparer,
    router,
)


TOKEN = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
RAW_TOKEN = bytes(range(32))
PROVISIONING_URI = (
    "otpauth://totp/Manita%20de%20Gato:Propietario?"
    "secret=JBSWY3DPEHPK3PXP&issuer=Manita%20de%20Gato"
)


class StubPreparer:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.tokens: list[bytes] = []

    def prepare(self, *, token: bytes) -> PreparedOwnerActivationSetup:
        self.tokens.append(token)
        if not self.available:
            raise OwnerActivationSetupError("internal setup state")
        return PreparedOwnerActivationSetup(
            provisioning_uri=PROVISIONING_URI,
            manual_key="JBSWY3DPEHPK3PXP",
        )


class StubAbandoner:
    def __init__(self) -> None:
        self.tokens: list[bytes] = []

    def abandon(self, *, token: bytes) -> None:
        self.tokens.append(token)


class StubCompleter:
    def __init__(self, *, rejection=None) -> None:
        self.rejection = rejection
        self.calls: list[dict[str, object]] = []

    def complete(self, *, token: bytes, password: str, totp_code: str):
        self.calls.append(
            {"token": token, "password": password, "totp_code": totp_code}
        )
        if self.rejection is not None:
            return OwnerActivationOutcome(rejection=self.rejection)
        return OwnerActivationOutcome(
            recovery_codes=tuple(
                f"ABCD-EFGH-JKLM-NPQ{character}"
                for character in "RSTUVWXYZ2"
            )
        )


def _client(
    preparer: StubPreparer,
    abandoner: StubAbandoner,
    completer: StubCompleter | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_owner_activation_preparer] = lambda: preparer
    app.dependency_overrides[get_owner_activation_abandoner] = lambda: abandoner
    app.dependency_overrides[get_owner_activation_completer] = lambda: (
        completer or StubCompleter()
    )
    return TestClient(app)


def test_t033_prepare_returns_only_unconfirmed_totp_material_without_cache() -> None:
    preparer = StubPreparer()
    with _client(preparer, StubAbandoner()) as client:
        response = client.post("/api/admin/security-links/prepare", json={"token": TOKEN})

    assert response.status_code == 200
    assert response.json() == {
        "totpSetup": {
            "provisioningUri": PROVISIONING_URI,
            "manualKey": "JBSWY3DPEHPK3PXP",
        }
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert preparer.tokens == [RAW_TOKEN]
    assert "password" not in response.text.lower()
    assert "recovery" not in response.text.lower()


def test_t033_prepare_uses_one_generic_result_for_an_unavailable_link() -> None:
    with _client(StubPreparer(available=False), StubAbandoner()) as client:
        response = client.post("/api/admin/security-links/prepare", json={"token": TOKEN})

    assert response.status_code == 404
    assert response.json() == {"detail": "Este enlace no es válido o ya no está disponible."}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "internal setup state" not in response.text


def test_t033_abandon_accepts_only_the_token_and_returns_no_content() -> None:
    abandoner = StubAbandoner()
    with _client(StubPreparer(), abandoner) as client:
        response = client.post("/api/admin/security-links/abandon", json={"token": TOKEN})

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert abandoner.tokens == [RAW_TOKEN]


def test_t034_completion_returns_ten_codes_once_without_starting_a_session() -> None:
    completer = StubCompleter()
    with _client(StubPreparer(), StubAbandoner(), completer) as client:
        response = client.post(
            "/api/admin/security-links/complete",
            json={
                "token": TOKEN,
                "password": "synthetic owner phrase 2033",
                "totpCode": "123456",
            },
        )

    assert response.status_code == 200
    assert len(response.json()["recoveryCodes"]) == 10
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "set-cookie" not in response.headers
    assert TOKEN not in response.text
    assert "synthetic owner phrase 2033" not in response.text
    assert completer.calls == [
        {
            "token": RAW_TOKEN,
            "password": "synthetic owner phrase 2033",
            "totp_code": "123456",
        }
    ]


def test_t034_completion_keeps_link_and_configuration_failures_generic() -> None:
    completer = StubCompleter(rejection="unavailable")
    with _client(StubPreparer(), StubAbandoner(), completer) as client:
        response = client.post(
            "/api/admin/security-links/complete",
            json={
                "token": TOKEN,
                "password": "synthetic owner phrase 2033",
                "totpCode": "123456",
            },
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Este enlace no es válido o ya no está disponible."}
    assert response.headers["cache-control"] == "no-store"
    assert "session" not in response.text.lower()


def test_t034_completion_reports_only_the_approved_password_error() -> None:
    completer = StubCompleter(rejection="invalid_password")
    with _client(StubPreparer(), StubAbandoner(), completer) as client:
        response = client.post(
            "/api/admin/security-links/complete",
            json={
                "token": TOKEN,
                "password": "synthetic owner phrase 2033",
                "totpCode": "123456",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "La contraseña no cumple los requisitos de seguridad."
    }
    assert "synthetic owner phrase 2033" not in response.text
