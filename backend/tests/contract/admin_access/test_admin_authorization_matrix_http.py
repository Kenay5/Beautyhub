"""T089 contract matrix for server-derived administrative permissions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeCapability,
    AdministrativeAuthorizationError,
    has_capability,
    require_capability,
    require_owner,
)
from backend.app.application.admin_access.administrative_history import (
    AdministrativeHistoryEntry,
)
from backend.app.application.admin_access.staff_invitation import (
    StaffInvitationDeliveryOutcome,
)
from backend.app.web.admin_auth.administrative_history import (
    get_administrative_history_operations,
    router as history_router,
)
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.app.web.admin_auth.staff_deactivation import (
    get_staff_deactivation_operations,
    router as staff_router,
)
from backend.app.web.admin_auth.staff_invitations import (
    get_staff_invitation_operations,
    router as invitations_router,
)


CAPABILITY_MATRIX: tuple[tuple[AdministrativeCapability, bool, bool], ...] = (
    ("manage_own_account_security", True, True),
    ("operate_appointments", True, True),
    ("retry_appointment_notifications", True, True),
    ("manage_services_and_prices", True, False),
    ("manage_staff_accounts", True, False),
    ("view_administrative_history", True, False),
)
HISTORY_ENTRY = AdministrativeHistoryEntry(
    event_id=7,
    actor_account_id=1,
    action="appointment_cancelled",
    result="succeeded",
    occurred_at=datetime(2026, 9, 26, 16, tzinfo=timezone.utc),
    target_reference="appointment:9",
)


@pytest.mark.parametrize(
    ("capability", "owner_allowed", "staff_allowed"),
    CAPABILITY_MATRIX,
)
def test_t089_central_policy_matrix_is_owner_staff_and_unauthenticated_safe(
    capability: AdministrativeCapability,
    owner_allowed: bool,
    staff_allowed: bool,
) -> None:
    owner = AdministrativeActor(account_id=1, role="owner")
    staff = AdministrativeActor(account_id=2, role="staff")

    assert has_capability(actor=owner, capability=capability) is owner_allowed
    assert has_capability(actor=staff, capability=capability) is staff_allowed
    assert has_capability(actor=None, capability=capability) is False  # type: ignore[arg-type]


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, **event: object) -> None:
        self.events.append(event)


class Operations:
    """Contract double that delegates all decisions to T082's central policy."""

    def __init__(self) -> None:
        self.audit = RecordingAudit()
        self.invites: list[tuple[int, str]] = []
        self.deactivations: list[int] = []
        self.history_reads: list[str] = []

    def invite(self, *, actor: AdministrativeActor, email: str):
        require_owner(actor=actor)
        self.invites.append((actor.account_id, email))
        return StaffInvitationDeliveryOutcome(accepted=True)

    def resend(self, *, actor: AdministrativeActor):
        require_owner(actor=actor)
        return StaffInvitationDeliveryOutcome(accepted=True)

    def cancel(self, *, actor: AdministrativeActor) -> None:
        require_owner(actor=actor)

    def status(self, *, actor: AdministrativeActor) -> str:
        require_owner(actor=actor)
        return "active"

    def deactivate(self, *, actor: AdministrativeActor) -> None:
        require_owner(actor=actor)
        self.deactivations.append(actor.account_id)

    def list_events(self, *, actor: AdministrativeActor, filters):
        require_capability(
            actor=actor,
            capability="view_administrative_history",
            audit=self.audit,
        )
        self.history_reads.append("list")
        return (HISTORY_ENTRY,), (1,)

    def get_event(self, *, actor: AdministrativeActor, event_id: int):
        require_capability(
            actor=actor,
            capability="view_administrative_history",
            audit=self.audit,
        )
        self.history_reads.append("detail")
        return HISTORY_ENTRY if event_id == HISTORY_ENTRY.event_id else None


def _client(*, actor: AdministrativeActor | None, operations: Operations) -> TestClient:
    app = FastAPI()
    app.include_router(invitations_router)
    app.include_router(staff_router)
    app.include_router(history_router)
    app.dependency_overrides[get_staff_invitation_operations] = lambda: operations
    app.dependency_overrides[get_staff_deactivation_operations] = lambda: operations
    app.dependency_overrides[get_administrative_history_operations] = lambda: operations
    app.dependency_overrides[require_administrative_mutation_protection] = lambda: None
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: _resolve_actor(actor)
    return TestClient(app)


def _resolve_actor(actor: AdministrativeActor | None) -> AdministrativeActor:
    if actor is None:
        raise HTTPException(
            status_code=401,
            detail="Autenticación administrativa requerida.",
        )
    return actor


@pytest.mark.parametrize(
    ("role", "expected_status"),
    (("owner", 201), ("staff", 403), (None, 401)),
    ids=("owner", "staff", "no-session"),
)
def test_t089_staff_account_contract_matrix_has_no_denied_side_effects(
    role: str | None,
    expected_status: int,
) -> None:
    actor = (
        None
        if role is None
        else AdministrativeActor(
            account_id=1 if role == "owner" else 2,
            role=role,  # type: ignore[arg-type]
        )
    )
    operations = Operations()

    with _client(actor=actor, operations=operations) as client:
        invite = client.post(
            "/api/admin/staff-invitations",
            json={"email": "synthetic.staff@example.test", "role": "owner", "accountId": 1},
            headers={"x-admin-role": "owner", "x-admin-account-id": "1"},
        )
        deactivate = client.post(
            "/api/admin/staff/deactivate",
            json={"role": "owner", "accountId": 1},
            headers={"x-admin-role": "owner", "x-admin-account-id": "1"},
        )

    assert invite.status_code == expected_status
    assert deactivate.status_code == (204 if role == "owner" else expected_status)
    assert operations.invites == (
        [(1, "synthetic.staff@example.test")] if role == "owner" else []
    )
    assert operations.deactivations == ([1] if role == "owner" else [])
    if role == "staff":
        assert invite.json() == deactivate.json()


@pytest.mark.parametrize(
    ("role", "expected_status"),
    (("owner", 200), ("staff", 403), (None, 401)),
    ids=("owner", "staff", "no-session"),
)
def test_t089_history_list_and_detail_contract_matrix(
    role: str | None,
    expected_status: int,
) -> None:
    actor = (
        None
        if role is None
        else AdministrativeActor(
            account_id=1 if role == "owner" else 2,
            role=role,  # type: ignore[arg-type]
        )
    )
    operations = Operations()

    with _client(actor=actor, operations=operations) as client:
        listing = client.get(
            "/api/admin/history",
            headers={"x-admin-role": "owner", "x-admin-account-id": "1"},
        )
        detail = client.get(
            "/api/admin/history/7",
            headers={"x-admin-role": "owner", "x-admin-account-id": "1"},
        )

    assert listing.status_code == expected_status
    assert detail.status_code == expected_status
    assert operations.history_reads == (["list", "detail"] if role == "owner" else [])
    assert all("private" not in response.text.lower() for response in (listing, detail))
    if role == "owner":
        assert listing.json()["events"][0]["targetReference"] == "appointment:9"
        assert detail.json()["targetReference"] == "appointment:9"


def test_t089_staff_denial_uses_the_shared_policy_and_records_minimal_audit() -> None:
    audit = RecordingAudit()
    staff = AdministrativeActor(account_id=2, role="staff")

    with pytest.raises(AdministrativeAuthorizationError):
        require_capability(
            actor=staff,
            capability="manage_services_and_prices",
            audit=audit,
        )

    assert audit.events == [
        {
            "actor_account_id": 2,
            "action": "authorization_denied",
            "result": "denied",
        }
    ]
