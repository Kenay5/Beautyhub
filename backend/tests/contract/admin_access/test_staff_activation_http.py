"""HTTP evidence for the T038 invited-staff activation adapter."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.staff_activation import (
    PreparedStaffActivationSetup,
    StaffActivationOutcome,
)
from backend.app.web.admin_auth.staff_activation import (
    get_staff_activation_abandoner,
    get_staff_activation_completer,
    get_staff_activation_preparer,
    router,
)


TOKEN = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"


class Preparer:
    def prepare(self, *, token):
        return PreparedStaffActivationSetup(
            provisioning_uri="otpauth://totp/Manita%20de%20Gato:Personal?secret=JBSWY3DPEHPK3PXP",
            manual_key="JBSWY3DPEHPK3PXP",
        )


class Abandoner:
    def __init__(self) -> None:
        self.called = False

    def abandon(self, *, token):
        self.called = True


class Completer:
    def complete(self, *, token, password, totp_code):
        return StaffActivationOutcome(
            recovery_codes=tuple(f"ABCD-EFGH-JKLM-NPQ{value}" for value in "RSTUVWXYZ2")
        )


def test_t038_staff_link_prepares_completes_and_abandons_without_session() -> None:
    app = FastAPI()
    app.include_router(router)
    abandoner = Abandoner()
    app.dependency_overrides[get_staff_activation_preparer] = lambda: Preparer()
    app.dependency_overrides[get_staff_activation_abandoner] = lambda: abandoner
    app.dependency_overrides[get_staff_activation_completer] = lambda: Completer()

    with TestClient(app) as client:
        prepared = client.post("/api/admin/staff-security-links/prepare", json={"token": TOKEN})
        completed = client.post(
            "/api/admin/staff-security-links/complete",
            json={"token": TOKEN, "password": "synthetic staff phrase", "totpCode": "123456"},
        )
        abandoned = client.post("/api/admin/staff-security-links/abandon", json={"token": TOKEN})

    assert prepared.status_code == 200
    assert prepared.json()["totpSetup"]["manualKey"] == "JBSWY3DPEHPK3PXP"
    assert completed.status_code == 200
    assert len(completed.json()["recoveryCodes"]) == 10
    assert abandoned.status_code == 204 and abandoner.called
    assert completed.cookies == {}
