"""T049 HTTP evidence that rejected mutation protection runs before effects."""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.mutation_protection import (
    ValidateAdministrativeMutationProtection,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.sessions.admin_session import AdminSession
from backend.app.application.admin_access.staff_invitation import (
    StaffInvitationDeliveryOutcome,
)
from backend.app.infrastructure.security.admin_session_protection import (
    AdminSessionProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.mutation_protection import (
    ADMINISTRATIVE_CSRF_HEADER,
    get_administrative_mutation_validator,
)
from backend.app.web.admin_auth.staff_invitations import (
    get_authenticated_admin_actor,
    get_staff_invitation_operations,
    router,
)


ORIGIN = "https://beautyhub.example.test"
SESSION_TOKEN = b"\x81" * 32
CSRF_TOKEN = b"\x82" * 32
WRONG_CSRF_TOKEN = b"\x83" * 32
NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)


def _protector() -> AdminSessionProtector:
    return AdminSessionProtector(
        key_ring=CryptographyKeyRing(
            CryptographyKeyConfiguration(
                root_key=SecretValue(
                    base64.urlsafe_b64encode(b"\x80" * 32).decode("ascii")
                ),
                key_version="v1",
            )
        )
    )


class SessionStore:
    def __init__(self) -> None:
        protector = _protector()
        self.session = AdminSession(
            account_id=7,
            session_digest=protector.digest_session_token(SESSION_TOKEN),
            csrf_digest=protector.digest_csrf_token(CSRF_TOKEN),
            key_version="v1",
            created_at=NOW,
            last_human_activity_at=NOW,
            absolute_expires_at=NOW + timedelta(hours=8),
            status="active",
            invalidated_at=None,
        )

    def load_active_session(self, *, session_digest):
        if session_digest != self.session.session_digest:
            return None
        return self.session

    def touch_human_activity(self, *, session_digest, current_time):
        return session_digest == self.session.session_digest

    def invalidate_if_expired(self, *, session_digest, current_time):
        return None


class RecordingOperations:
    def __init__(self) -> None:
        self.calls = []

    def invite(self, *, actor, email):
        self.calls.append((actor, email))
        return StaffInvitationDeliveryOutcome(accepted=True)

    def resend(self, *, actor):
        raise AssertionError("unexpected operation")

    def cancel(self, *, actor):
        raise AssertionError("unexpected operation")


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client(operations: RecordingOperations) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: AdministrativeActor(
        account_id=7,
        role="owner",
    )
    app.dependency_overrides[get_staff_invitation_operations] = lambda: operations
    app.dependency_overrides[get_administrative_mutation_validator] = lambda: (
        ValidateAdministrativeMutationProtection(
            store=SessionStore(),
            protector=_protector(),
            clock=FixedClock(NOW),
        )
    )
    return TestClient(app, base_url=ORIGIN)


def _request(client: TestClient, *, session=SESSION_TOKEN, csrf=CSRF_TOKEN, origin=ORIGIN):
    headers = {}
    if session is not None:
        headers["cookie"] = f"{ADMINISTRATIVE_SESSION_COOKIE}={_encoded(session)}"
    if csrf is not None:
        headers[ADMINISTRATIVE_CSRF_HEADER] = _encoded(csrf)
    if origin is not None:
        headers["origin"] = origin
    return client.post(
        "/api/admin/staff-invitations",
        headers=headers,
        json={"email": "synthetic.staff@example.test"},
    )


def test_t049_valid_same_origin_csrf_allows_the_mutation() -> None:
    operations = RecordingOperations()
    with _client(operations) as client:
        response = _request(client)

    assert response.status_code == 201
    assert len(operations.calls) == 1


@pytest.mark.parametrize(
    ("csrf", "origin"),
    (
        (None, ORIGIN),
        (WRONG_CSRF_TOKEN, ORIGIN),
        (CSRF_TOKEN, None),
        (CSRF_TOKEN, "https://foreign.example.test"),
    ),
)
def test_t049_invalid_csrf_or_origin_returns_403_before_any_effect(csrf, origin) -> None:
    operations = RecordingOperations()
    with _client(operations) as client:
        response = _request(client, csrf=csrf, origin=origin)

    assert response.status_code == 403
    assert response.json() == {
        "detail": "No tienes permiso para realizar esta operación."
    }
    assert operations.calls == []


def test_t049_missing_session_returns_401_before_any_effect() -> None:
    operations = RecordingOperations()
    with _client(operations) as client:
        response = _request(client, session=None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Autenticación administrativa requerida."}
    assert operations.calls == []
