"""T074 unit evidence for the public appointment modification field whitelist."""

from __future__ import annotations

import pytest

from backend.app.application.public_appointment_modification_fields import (
    PublicAppointmentModificationFieldError,
    require_only_public_appointment_modification_fields,
)


@pytest.mark.parametrize(
    "changes",
    (
        {"scheduledStart": "2030-06-01T11:00:00-06:00"},
        {"branch": "chiconcuac"},
        {"serviceName": "Servicio sintético"},
        {
            "scheduledStart": "2030-06-01T11:00:00-06:00",
            "branch": "texcoco",
            "serviceName": "Servicio sintético",
        },
    ),
)
def test_t074_accepts_only_the_approved_public_appointment_fields(
    changes: dict[str, object],
) -> None:
    require_only_public_appointment_modification_fields(changes)


@pytest.mark.parametrize(
    "field",
    ("firstName", "lastName", "phone", "email"),
)
def test_t074_rejects_each_public_attempt_to_change_name_or_contact(
    field: str,
) -> None:
    with pytest.raises(PublicAppointmentModificationFieldError):
        require_only_public_appointment_modification_fields(
            {
                "scheduledStart": "2030-06-01T11:00:00-06:00",
                field: "synthetic-unapproved-value",
            }
        )


def test_t074_rejects_an_unapproved_field_even_alongside_valid_changes() -> None:
    with pytest.raises(PublicAppointmentModificationFieldError):
        require_only_public_appointment_modification_fields(
            {
                "branch": "texcoco",
                "status": "cancelled",
            }
        )
