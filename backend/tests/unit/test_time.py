"""Unit tests for BeautyHub official-zone temporal rules."""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from backend.app.domain.time import (
    BUSINESS_TIME_ZONE,
    InstantValidationError,
    business_datetime,
    normalize_instant,
    to_business_time,
)


def test_normalize_instant_treats_equivalent_zones_as_the_same_absolute_time() -> None:
    utc_instant = datetime(2030, 6, 15, 18, tzinfo=timezone.utc)
    offset_instant = datetime(
        2030,
        6,
        15,
        12,
        tzinfo=timezone(timedelta(hours=-6)),
    )

    assert normalize_instant(utc_instant) == normalize_instant(offset_instant)


def test_to_business_time_converts_an_absolute_instant_to_official_zone() -> None:
    business_time = to_business_time(datetime(2030, 6, 15, 18, tzinfo=timezone.utc))

    assert business_time == datetime(2030, 6, 15, 12, tzinfo=BUSINESS_TIME_ZONE)


def test_business_datetime_creates_an_explicit_official_zone_instant() -> None:
    instant = business_datetime(date(2030, 6, 15), time(9, 0))

    assert instant == datetime(2030, 6, 15, 9, tzinfo=BUSINESS_TIME_ZONE)
    assert normalize_instant(instant) == datetime(2030, 6, 15, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "instant", [datetime(2030, 6, 15, 9), "2030-06-15T09:00:00"]
)
def test_normalize_instant_rejects_values_without_an_explicit_zone(
    instant: object,
) -> None:
    with pytest.raises(InstantValidationError):
        normalize_instant(instant)  # type: ignore[arg-type]


def test_business_datetime_rejects_a_time_that_already_has_a_zone() -> None:
    with pytest.raises(InstantValidationError, match="must not include"):
        business_datetime(date(2030, 6, 15), time(9, tzinfo=timezone.utc))
