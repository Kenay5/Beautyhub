"""T083 evidence that final public appointment states are immutable."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.application.authorize_public_appointment_modification import (
    is_public_appointment_state_modifiable,
)
from backend.app.application.cancel_public_appointment import (
    is_public_appointment_cancellation_allowed,
)
from backend.app.application.public_appointment_modification_fields import (
    PublicAppointmentModificationFieldError,
    require_only_public_appointment_modification_fields,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
FINAL_STATUSES = ("cancelled", "completed", "no_show", "unrecorded_result")


@pytest.mark.parametrize("status", FINAL_STATUSES)
def test_t083_final_states_cannot_be_modified_or_cancelled(status: str) -> None:
    scheduled_start = NOW + timedelta(hours=2)

    assert not is_public_appointment_state_modifiable(
        status=status,
        scheduled_start=scheduled_start,
        current_time=NOW,
    )
    assert not is_public_appointment_cancellation_allowed(
        status=status,
        scheduled_start=scheduled_start,
        current_time=NOW,
    )


def test_t083_public_mutations_cannot_submit_a_status_to_reactivate_an_appointment() -> None:
    with pytest.raises(PublicAppointmentModificationFieldError):
        require_only_public_appointment_modification_fields(
            {
                "scheduledStart": "2030-06-02T11:00:00-06:00",
                "status": "scheduled",
            }
        )
