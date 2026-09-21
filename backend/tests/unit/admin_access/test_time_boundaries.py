"""T004 evidence for the shared clock and official business time zone."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from backend.app.application.clock import FixedClock
from backend.app.domain.time import BUSINESS_TIME_ZONE, business_datetime, to_business_time


def test_t004_uses_the_shared_fixed_clock_without_a_second_clock() -> None:
    instant = datetime(2030, 1, 15, 18, 30, tzinfo=timezone.utc)
    clock = FixedClock(instant)

    assert clock.now() == instant
    assert to_business_time(clock.now()).tzinfo == BUSINESS_TIME_ZONE


def test_t004_builds_administrative_deadlines_in_mexico_city_time() -> None:
    local_start = business_datetime(date(2030, 1, 15), time(12, 30))

    assert local_start.tzinfo == BUSINESS_TIME_ZONE
    assert local_start.astimezone(timezone.utc) == datetime(
        2030, 1, 15, 18, 30, tzinfo=timezone.utc
    )
