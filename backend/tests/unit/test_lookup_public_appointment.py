"""T061 unit evidence for exact public private-code lookup."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.app.application.lookup_public_appointment import (
    LookupPublicAppointment,
    PUBLIC_APPOINTMENT_CREDENTIAL_ERROR_DETAIL,
    PublicAppointmentCredentialError,
    PublicAppointmentLookupError,
    PublicAppointmentRecord,
    require_matching_public_appointment_phone,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.time import BUSINESS_TIME_ZONE


class RecordingDigester:
    """Controlled keyed-digest boundary for public-code lookup."""

    def __init__(self) -> None:
        self.secrets: list[str] = []

    def digest(self, secret: str) -> bytes:
        self.secrets.append(secret)
        return b"private-code-fingerprint"


class DigestOnlyReader:
    """Reader double intentionally offering no personal-data search operation."""

    def __init__(self, result: PublicAppointmentRecord | None) -> None:
        self.result = result
        self.digests: list[bytes] = []

    def find_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> PublicAppointmentRecord | None:
        self.digests.append(private_code_digest)
        return self.result


class MalformedCodeDigester:
    """Simulate protected-code parsing without exposing its internal failure."""

    def digest(self, secret: str) -> bytes:
        raise ValueError("private code parser diagnostic")


def test_t061_returns_only_the_appointment_for_the_private_code_fingerprint() -> None:
    digester = RecordingDigester()
    expected = _record("Manicure sintético")
    reader = DigestOnlyReader(expected)

    result = LookupPublicAppointment(
        reader=reader,
        secret_digester=digester,
        clock=FixedClock(datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)),
    ).execute("synthetic-private-code")

    assert result == expected
    assert digester.secrets == ["synthetic-private-code"]
    assert reader.digests == [b"private-code-fingerprint"]
    assert not hasattr(result, "private_code_digest")
    assert not hasattr(result, "private_code_ciphertext")
    assert not hasattr(result, "appointment_id")


def test_t061_rejects_a_missing_private_code_without_a_personal_data_lookup() -> None:
    digester = RecordingDigester()
    reader = DigestOnlyReader(None)
    lookup = _lookup(reader=reader, digester=digester)

    with pytest.raises(PublicAppointmentLookupError):
        lookup.execute("synthetic-private-code")

    assert digester.secrets == ["synthetic-private-code"]
    assert reader.digests == [b"private-code-fingerprint"]


@pytest.mark.parametrize("value", (None, ""))
def test_t061_rejects_absent_private_codes_before_lookup(value: object) -> None:
    digester = RecordingDigester()
    reader = DigestOnlyReader(_record("No debe consultarse"))

    with pytest.raises(PublicAppointmentLookupError):
        _lookup(reader=reader, digester=digester).execute(  # type: ignore[arg-type]
            value
        )

    assert digester.secrets == []
    assert reader.digests == []


@pytest.mark.parametrize(
    "status",
    ("scheduled", "cancelled", "completed", "no_show", "unrecorded_result"),
)
def test_t063_all_appointment_states_remain_publicly_available_through_235959(
    status: str,
) -> None:
    record = _record("Servicio vigente", status=status)
    reader = DigestOnlyReader(record)
    lookup = _lookup(
        reader=reader,
        clock=FixedClock(datetime(2030, 7, 2, 23, 59, 59, tzinfo=BUSINESS_TIME_ZONE)),
    )

    assert lookup.execute("synthetic-private-code") == record


def test_t063_denies_public_lookup_at_the_following_local_midnight() -> None:
    reader = DigestOnlyReader(_record("Servicio vencido"))
    lookup = _lookup(
        reader=reader,
        clock=FixedClock(datetime(2030, 7, 3, 0, 0, tzinfo=BUSINESS_TIME_ZONE)),
    )

    with pytest.raises(PublicAppointmentLookupError):
        lookup.execute("synthetic-private-code")


def test_t063_evaluates_calendar_limits_in_the_business_time_zone() -> None:
    record = _record(
        "Servicio con instante UTC",
        scheduled_start=datetime(2030, 6, 3, 0, 30, tzinfo=timezone.utc),
    )
    reader = DigestOnlyReader(record)
    still_current = _lookup(
        reader=reader,
        clock=FixedClock(datetime(2030, 7, 3, 5, 59, 59, tzinfo=timezone.utc)),
    )
    expired = _lookup(
        reader=reader,
        clock=FixedClock(datetime(2030, 7, 3, 6, tzinfo=timezone.utc)),
    )

    assert still_current.execute("synthetic-private-code") == record
    with pytest.raises(PublicAppointmentLookupError):
        expired.execute("synthetic-private-code")


def test_t064_uses_one_indistinguishable_error_for_public_code_failures() -> None:
    nonexistent = _credential_failure(
        _lookup(reader=DigestOnlyReader(None)),
        "synthetic-private-code",
    )
    malformed = _credential_failure(
        LookupPublicAppointment(
            reader=DigestOnlyReader(_record("Servicio de prueba")),
            secret_digester=MalformedCodeDigester(),
            clock=FixedClock(datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)),
        ),
        "not-ascii-\N{SNOWMAN}",
    )
    expired = _credential_failure(
        _lookup(
            reader=DigestOnlyReader(_record("Servicio vencido")),
            clock=FixedClock(datetime(2030, 7, 3, 0, tzinfo=BUSINESS_TIME_ZONE)),
        ),
        "synthetic-private-code",
    )

    assert all(isinstance(error, PublicAppointmentCredentialError) for error in (
        nonexistent,
        malformed,
        expired,
    ))
    assert {str(error) for error in (nonexistent, malformed, expired)} == {
        PUBLIC_APPOINTMENT_CREDENTIAL_ERROR_DETAIL
    }
    assert "parser diagnostic" not in str(malformed)


@pytest.mark.parametrize("provided_phone", ("5510000001", "invalido"))
def test_t064_returns_that_same_error_for_a_wrong_public_phone(
    provided_phone: str,
) -> None:
    with pytest.raises(PublicAppointmentCredentialError) as error:
        require_matching_public_appointment_phone(
            provided_phone=provided_phone,
            registered_phone="5510000000",
        )

    assert str(error.value) == PUBLIC_APPOINTMENT_CREDENTIAL_ERROR_DETAIL


def _lookup(
    *,
    reader: DigestOnlyReader,
    digester: RecordingDigester | None = None,
    clock: FixedClock | None = None,
) -> LookupPublicAppointment:
    return LookupPublicAppointment(
        reader=reader,
        secret_digester=digester or RecordingDigester(),
        clock=clock
        or FixedClock(datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)),
    )


def _credential_failure(
    lookup: LookupPublicAppointment,
    private_code: str,
) -> PublicAppointmentCredentialError:
    with pytest.raises(PublicAppointmentCredentialError) as error:
        lookup.execute(private_code)
    return error.value


def _record(
    service_name: str,
    *,
    status: str = "scheduled",
    scheduled_start: datetime | None = None,
) -> PublicAppointmentRecord:
    return PublicAppointmentRecord(
        service_name=service_name,
        duration_minutes=60,
        price=Decimal("350.00"),
        branch="chiconcuac",
        scheduled_start=scheduled_start
        or datetime(2030, 6, 2, 11, tzinfo=BUSINESS_TIME_ZONE),
        status=status,
        phone="5510000000",
        email="clienta@example.test",
    )
