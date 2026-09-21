"""Unit tests for public availability calculation."""

from datetime import date, time, timedelta

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.list_public_availability import (
    ListPublicAvailability,
    PublicAvailabilityValidationError,
)
from backend.app.domain.schedule import ScheduledInterval, TimeInterval
from backend.app.domain.time import business_datetime


class FakePublicAvailabilityReader:
    """Controlled state for availability use-case tests."""

    def __init__(
        self,
        *,
        duration_minutes: int | None = 60,
        scheduled_intervals: tuple[ScheduledInterval, ...] = (),
        blocks: tuple[TimeInterval, ...] = (),
    ) -> None:
        self.duration_minutes = duration_minutes
        self.scheduled_intervals = scheduled_intervals
        self.blocks = blocks

    def get_active_service_duration(self, branch: str, service_name: str) -> int | None:
        return self.duration_minutes if service_name == "Manicure" else None

    def list_scheduled_intervals(self) -> tuple[ScheduledInterval, ...]:
        return self.scheduled_intervals

    def list_applicable_blocks(self, branch: str) -> tuple[TimeInterval, ...]:
        return self.blocks


def test_public_availability_returns_only_starts_that_respect_notice_blocks_and_buffers() -> None:
    appointment_date = date(2030, 6, 15)
    reader = FakePublicAvailabilityReader(
        scheduled_intervals=(
            ScheduledInterval(
                TimeInterval(
                    business_datetime(appointment_date, time(10)),
                    business_datetime(appointment_date, time(11)),
                ),
                "chiconcuac",
            ),
        ),
        blocks=(
            TimeInterval(
                business_datetime(appointment_date, time(11, 15)),
                business_datetime(appointment_date, time(12, 15)),
            ),
        ),
    )
    availability = ListPublicAvailability(
        reader,
        FixedClock(business_datetime(appointment_date, time(10))),
    )

    starts = availability.execute(
        branch="chiconcuac",
        service_name="Manicure",
        appointment_date=appointment_date,
    )

    assert starts[0] == business_datetime(appointment_date, time(12, 15))
    assert business_datetime(appointment_date, time(10, 45)) not in starts
    assert business_datetime(appointment_date, time(11, 15)) not in starts


def test_public_availability_applies_cross_branch_buffer_to_the_single_professional() -> None:
    appointment_date = date(2030, 6, 15)
    reader = FakePublicAvailabilityReader(
        scheduled_intervals=(
            ScheduledInterval(
                TimeInterval(
                    business_datetime(appointment_date, time(9)),
                    business_datetime(appointment_date, time(10)),
                ),
                "chiconcuac",
            ),
        ),
    )
    availability = ListPublicAvailability(
        reader,
        FixedClock(business_datetime(appointment_date, time(7))),
    )

    starts = availability.execute(
        branch="texcoco",
        service_name="Manicure",
        appointment_date=appointment_date,
    )

    assert business_datetime(appointment_date, time(10, 15)) not in starts
    assert business_datetime(appointment_date, time(10, 30)) in starts


def test_public_availability_rejects_a_service_that_is_not_publicly_bookable() -> None:
    availability = ListPublicAvailability(
        FakePublicAvailabilityReader(duration_minutes=None),
        FixedClock(business_datetime(date(2030, 6, 15), time(7))),
    )

    with pytest.raises(PublicAvailabilityValidationError):
        availability.execute(
            branch="chiconcuac",
            service_name="Manicure",
            appointment_date=date(2030, 6, 15),
        )


@pytest.mark.parametrize(
    "appointment_date",
    [
        "2030-06-15",
        business_datetime(date(2030, 6, 15), time(9)),
    ],
)
def test_public_availability_rejects_a_non_calendar_date(appointment_date: object) -> None:
    availability = ListPublicAvailability(
        FakePublicAvailabilityReader(),
        FixedClock(business_datetime(date(2030, 6, 15), time(7))),
    )

    with pytest.raises(PublicAvailabilityValidationError):
        availability.execute(
            branch="chiconcuac",
            service_name="Manicure",
            appointment_date=appointment_date,  # type: ignore[arg-type]
        )
