"""T073 unit evidence for public appointment modification authorization."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from backend.app.application.authorize_public_appointment_modification import (
    AuthorizePublicAppointmentModification,
    PublicAppointmentModificationNotPermittedError,
)
from backend.app.application.clock import FixedClock
from backend.app.application.lookup_public_appointment import (
    LookupPublicAppointment,
    PublicAppointmentCredentialError,
    PublicAppointmentRecord,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
PRIVATE_CODE = "synthetic-private-code-not-for-production"
REGISTERED_PHONE = "5510000000"


class RecordingDigester:
    """Provide one controlled private-code digest for authorization tests."""

    def __init__(self) -> None:
        self.secrets: list[str] = []

    def digest(self, secret: str) -> bytes:
        self.secrets.append(secret)
        return b"synthetic-private-code-digest"


class ExactDigestReader:
    """Expose only the approved exact-digest lookup operation."""

    def __init__(self, appointment: PublicAppointmentRecord | None) -> None:
        self._appointment = appointment
        self.digests: list[bytes] = []

    def find_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> PublicAppointmentRecord | None:
        self.digests.append(private_code_digest)
        return self._appointment


def test_t073_authorizes_a_scheduled_appointment_exactly_sixty_minutes_before_start() -> None:
    authorization, digester, reader = _authorization(
        _appointment(scheduled_start=NOW + timedelta(hours=1)),
    )

    authorization.execute(private_code=PRIVATE_CODE, phone="55 1000 0000")

    assert digester.secrets == [PRIVATE_CODE]
    assert reader.digests == [b"synthetic-private-code-digest"]


@pytest.mark.parametrize(
    "status",
    ("cancelled", "completed", "no_show", "unrecorded_result"),
)
def test_t073_rejects_each_non_scheduled_appointment_state(status: str) -> None:
    authorization, _, _ = _authorization(
        _appointment(status=status, scheduled_start=NOW + timedelta(hours=2)),
    )

    with pytest.raises(PublicAppointmentModificationNotPermittedError):
        authorization.execute(private_code=PRIVATE_CODE, phone=REGISTERED_PHONE)


def test_t073_rejects_one_second_inside_the_sixty_minute_notice_boundary() -> None:
    authorization, _, _ = _authorization(
        _appointment(scheduled_start=NOW + timedelta(hours=1) - timedelta(seconds=1)),
    )

    with pytest.raises(PublicAppointmentModificationNotPermittedError):
        authorization.execute(private_code=PRIVATE_CODE, phone=REGISTERED_PHONE)


@pytest.mark.parametrize("phone", ("5510000001", "not-a-phone"))
def test_t073_rejects_an_incorrect_public_phone_with_the_existing_generic_error(
    phone: str,
) -> None:
    authorization, _, _ = _authorization(
        _appointment(scheduled_start=NOW + timedelta(hours=2)),
    )

    with pytest.raises(PublicAppointmentCredentialError):
        authorization.execute(private_code=PRIVATE_CODE, phone=phone)


def test_t073_rejects_an_unknown_private_code_before_it_can_continue() -> None:
    authorization, digester, reader = _authorization(None)

    with pytest.raises(PublicAppointmentCredentialError):
        authorization.execute(private_code=PRIVATE_CODE, phone=REGISTERED_PHONE)

    assert digester.secrets == [PRIVATE_CODE]
    assert reader.digests == [b"synthetic-private-code-digest"]


def _authorization(
    appointment: PublicAppointmentRecord | None,
) -> tuple[AuthorizePublicAppointmentModification, RecordingDigester, ExactDigestReader]:
    digester = RecordingDigester()
    reader = ExactDigestReader(appointment)
    clock = FixedClock(NOW)
    lookup = LookupPublicAppointment(
        reader=reader,
        secret_digester=digester,
        clock=clock,
    )
    return (
        AuthorizePublicAppointmentModification(lookup=lookup, clock=clock),
        digester,
        reader,
    )


def _appointment(
    *,
    status: str = "scheduled",
    scheduled_start: datetime,
) -> PublicAppointmentRecord:
    return PublicAppointmentRecord(
        service_name="Servicio sintético",
        duration_minutes=60,
        price=Decimal("350.00"),
        branch="chiconcuac",
        scheduled_start=scheduled_start,
        status=status,
        phone=REGISTERED_PHONE,
        email="clienta@example.test",
    )
