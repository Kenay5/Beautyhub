"""T082 unit evidence for the centralized administrative capability policy."""

from __future__ import annotations

import pytest

from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
    has_capability,
    require_capability,
    require_owner,
)


@pytest.mark.parametrize("role", ("owner", "staff"))
def test_t082_owner_and_staff_can_operate_appointments_and_retry_registered_notices(
    role: str,
) -> None:
    actor = AdministrativeActor(account_id=7, role=role)  # type: ignore[arg-type]

    assert has_capability(actor=actor, capability="operate_appointments")
    assert has_capability(
        actor=actor, capability="retry_appointment_notifications"
    )
    require_capability(actor=actor, capability="retry_appointment_notifications")


def test_t082_staff_cannot_manage_services_staff_accounts_or_history() -> None:
    staff = AdministrativeActor(account_id=8, role="staff")

    for capability in (
        "manage_services_and_prices",
        "manage_staff_accounts",
        "view_administrative_history",
    ):
        assert not has_capability(actor=staff, capability=capability)
        with pytest.raises(AdministrativeAuthorizationError):
            require_capability(actor=staff, capability=capability)

    with pytest.raises(AdministrativeAuthorizationError):
        require_owner(actor=staff)


def test_t082_only_owner_can_administer_accounts() -> None:
    owner = AdministrativeActor(account_id=1, role="owner")
    another_account = AdministrativeActor(account_id=8, role="staff")

    require_owner(actor=owner)
    with pytest.raises(AdministrativeAuthorizationError):
        require_owner(actor=another_account)


def test_t082_untrusted_actor_objects_have_no_capabilities() -> None:
    with pytest.raises(AdministrativeAuthorizationError):
        require_capability(
            actor=None,  # type: ignore[arg-type]
            capability="retry_appointment_notifications",
        )


def test_t083_authenticated_denial_records_only_minimum_actor_action_and_result() -> None:
    class Audit:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def record(self, **event: object) -> None:
            self.events.append(event)

    audit = Audit()
    staff = AdministrativeActor(account_id=8, role="staff")

    with pytest.raises(AdministrativeAuthorizationError):
        require_capability(
            actor=staff,
            capability="manage_services_and_prices",
            audit=audit,
        )

    assert audit.events == [
        {
            "actor_account_id": 8,
            "action": "authorization_denied",
            "result": "denied",
        }
    ]


def test_t083_denial_without_identifiable_actor_does_not_write_audit() -> None:
    class Audit:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def record(self, **event: object) -> None:
            self.events.append(event)

    audit = Audit()

    with pytest.raises(AdministrativeAuthorizationError):
        require_capability(
            actor=None,  # type: ignore[arg-type]
            capability="manage_services_and_prices",
            audit=audit,
        )

    assert audit.events == []
