"""T016 unit evidence for minimum, non-private administrative audit events."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.domain.audit.admin_audit_event import (
    AdministrativeAuditEvent,
    AdministrativeAuditEventInvariantError,
)


NOW = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)


def test_t016_accepts_an_identified_or_anonymous_minimum_event() -> None:
    identified = AdministrativeAuditEvent(
        actor_account_id=7,
        action="appointment_modified",
        result="succeeded",
        occurred_at=NOW,
        target_reference="appointment:13",
    )
    anonymous = AdministrativeAuditEvent(
        actor_account_id=None,
        action="login",
        result="failed",
        occurred_at=NOW,
        target_reference=None,
    )

    assert identified.actor_account_id == 7
    assert anonymous.actor_account_id is None
    assert "email" not in identified.__dataclass_fields__
    assert "password" not in identified.__dataclass_fields__


@pytest.mark.parametrize(
    "target_reference",
    ("client@example.test", "phone:5551234567", "appointment:01", "Appointment:1"),
)
def test_t016_rejects_non_internal_or_private_target_references(
    target_reference: str,
) -> None:
    with pytest.raises(AdministrativeAuditEventInvariantError):
        AdministrativeAuditEvent(
            actor_account_id=7,
            action="appointment_modified",
            result="succeeded",
            occurred_at=NOW,
            target_reference=target_reference,
        )
