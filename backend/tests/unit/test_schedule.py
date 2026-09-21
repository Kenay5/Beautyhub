"""Unit tests for BeautyHub daily appointment-start grid rules."""

from datetime import date, datetime, time, timedelta

import pytest

from backend.app.domain.schedule import (
    TimeInterval,
    ScheduledInterval,
    administrative_same_day_alternative_suggestion,
    appointment_end,
    daily_start_times,
    earliest_administrative_start,
    earliest_cross_branch_start,
    earliest_same_branch_start,
    has_cross_branch_separation_conflict,
    has_neighbor_separation_conflict,
    has_schedule_conflict,
    has_same_branch_separation_conflict,
    nearest_same_day_alternatives,
    occupying_intervals,
    public_same_day_alternative_suggestion,
    same_day_alternative_suggestion,
    validate_administrative_appointment_timing,
    validate_public_appointment_timing,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE, InstantValidationError, business_datetime


def test_daily_start_times_include_the_approved_business_bounds() -> None:
    starts = daily_start_times(date(2030, 6, 15))

    assert starts[0] == datetime(2030, 6, 15, 9, tzinfo=BUSINESS_TIME_ZONE)
    assert starts[-1] == datetime(2030, 6, 15, 19, tzinfo=BUSINESS_TIME_ZONE)


def test_daily_start_times_use_fifteen_minute_intervals() -> None:
    starts = daily_start_times(date(2030, 6, 15))

    assert len(starts) == 41
    assert all(
        following - current == timedelta(minutes=15)
        for current, following in zip(starts, starts[1:], strict=False)
    )


@pytest.mark.parametrize("local_date", [date(2030, 6, 16), date(2030, 6, 17)])
def test_daily_start_times_apply_on_every_business_weekday(local_date: date) -> None:
    starts = daily_start_times(local_date)

    assert len(starts) == 41
    assert {start.date() for start in starts} == {local_date}


def test_daily_start_times_reject_a_datetime_as_a_local_date() -> None:
    with pytest.raises(InstantValidationError, match="local date must be a date"):
        daily_start_times(datetime(2030, 6, 15, 9))


def test_lunch_start_is_permitted_by_daily_start_grid() -> None:
    local_date = date(2030, 6, 15)

    assert business_datetime(local_date, time(13)) in daily_start_times(local_date)


def test_appointment_can_continue_during_lunch_period() -> None:
    local_date = date(2030, 6, 15)
    start = business_datetime(local_date, time(12, 45))

    assert appointment_end(start, timedelta(minutes=30)) == business_datetime(
        local_date,
        time(13, 15),
    )


def test_appointment_starting_at_last_start_can_end_after_business_hours() -> None:
    local_date = date(2030, 6, 15)
    start = business_datetime(local_date, time(19))

    assert start in daily_start_times(local_date)
    assert appointment_end(start, timedelta(minutes=90)) == business_datetime(
        local_date,
        time(20, 30),
    )


def test_time_interval_includes_its_start_and_excludes_its_exact_end() -> None:
    local_date = date(2030, 6, 15)
    interval = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(11)),
    )

    assert interval.contains(business_datetime(local_date, time(10)))
    assert not interval.contains(business_datetime(local_date, time(11)))


def test_appointment_and_block_can_touch_at_their_exact_boundary() -> None:
    local_date = date(2030, 6, 15)
    appointment = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(11)),
    )
    block = TimeInterval(
        business_datetime(local_date, time(11)),
        business_datetime(local_date, time(12)),
    )

    assert not appointment.overlaps(block)
    assert not block.overlaps(appointment)


def test_time_intervals_overlap_when_they_share_an_occupied_instant() -> None:
    local_date = date(2030, 6, 15)
    first = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(11)),
    )
    second = TimeInterval(
        business_datetime(local_date, time(10, 30)),
        business_datetime(local_date, time(11, 30)),
    )

    assert first.overlaps(second)


def test_schedule_rejects_an_overlapping_appointment_in_the_same_branch() -> None:
    local_date = date(2030, 6, 15)
    existing_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(11)),
    )
    candidate_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10, 30)),
        business_datetime(local_date, time(11, 30)),
    )

    assert has_schedule_conflict(
        candidate_chiconcuac_appointment,
        (existing_chiconcuac_appointment,),
    )


def test_schedule_rejects_an_overlapping_appointment_in_the_other_branch() -> None:
    local_date = date(2030, 6, 15)
    existing_texcoco_appointment = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(11)),
    )
    candidate_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10, 30)),
        business_datetime(local_date, time(11, 30)),
    )

    assert has_schedule_conflict(
        candidate_chiconcuac_appointment,
        (existing_texcoco_appointment,),
    )


def test_schedule_allows_a_candidate_at_an_existing_appointment_exact_end() -> None:
    local_date = date(2030, 6, 15)
    existing_texcoco_appointment = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(11)),
    )
    candidate_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(11)),
        business_datetime(local_date, time(12)),
    )

    assert not has_schedule_conflict(
        candidate_chiconcuac_appointment,
        (existing_texcoco_appointment,),
    )


def test_same_branch_requires_five_minutes_after_the_previous_appointment() -> None:
    local_date = date(2030, 6, 15)
    previous_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(10, 15)),
    )
    too_early_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10, 15)),
        business_datetime(local_date, time(11)),
    )

    assert has_same_branch_separation_conflict(
        previous_chiconcuac_appointment,
        too_early_chiconcuac_appointment,
    )


def test_same_branch_uses_the_first_grid_start_after_the_five_minute_buffer() -> None:
    local_date = date(2030, 6, 15)
    previous_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(10, 15)),
    )

    assert earliest_same_branch_start(previous_chiconcuac_appointment) == business_datetime(
        local_date,
        time(10, 30),
    )


def test_same_branch_keeps_an_exact_grid_start_after_the_buffer() -> None:
    local_date = date(2030, 6, 15)
    previous_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(10, 10)),
    )
    candidate_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10, 15)),
        business_datetime(local_date, time(11)),
    )

    assert earliest_same_branch_start(previous_chiconcuac_appointment) == candidate_chiconcuac_appointment.start
    assert not has_same_branch_separation_conflict(
        previous_chiconcuac_appointment,
        candidate_chiconcuac_appointment,
    )


def test_cross_branch_requires_twenty_five_minutes_after_the_previous_appointment() -> None:
    local_date = date(2030, 6, 15)
    previous_texcoco_appointment = TimeInterval(
        business_datetime(local_date, time(9)),
        business_datetime(local_date, time(10)),
    )
    too_early_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10, 15)),
        business_datetime(local_date, time(11)),
    )

    assert has_cross_branch_separation_conflict(
        previous_texcoco_appointment,
        too_early_chiconcuac_appointment,
    )


def test_cross_branch_uses_the_first_grid_start_after_the_twenty_five_minute_buffer() -> None:
    local_date = date(2030, 6, 15)
    previous_texcoco_appointment = TimeInterval(
        business_datetime(local_date, time(9)),
        business_datetime(local_date, time(10)),
    )

    assert earliest_cross_branch_start(previous_texcoco_appointment) == business_datetime(
        local_date,
        time(10, 30),
    )


def test_cross_branch_keeps_an_exact_grid_start_after_the_buffer() -> None:
    local_date = date(2030, 6, 15)
    previous_texcoco_appointment = TimeInterval(
        business_datetime(local_date, time(9)),
        business_datetime(local_date, time(10, 5)),
    )
    candidate_chiconcuac_appointment = TimeInterval(
        business_datetime(local_date, time(10, 30)),
        business_datetime(local_date, time(11)),
    )

    assert earliest_cross_branch_start(previous_texcoco_appointment) == candidate_chiconcuac_appointment.start
    assert not has_cross_branch_separation_conflict(
        previous_texcoco_appointment,
        candidate_chiconcuac_appointment,
    )


def test_candidate_rejects_an_insufficient_separation_from_its_previous_neighbor() -> None:
    local_date = date(2030, 6, 15)
    previous = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(9)),
            business_datetime(local_date, time(10)),
        ),
        "chiconcuac",
    )
    candidate = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(10)),
            business_datetime(local_date, time(10, 30)),
        ),
        "chiconcuac",
    )

    assert has_neighbor_separation_conflict(candidate, previous, None)


def test_candidate_rejects_an_insufficient_separation_from_its_following_neighbor() -> None:
    local_date = date(2030, 6, 15)
    candidate = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(10)),
            business_datetime(local_date, time(10, 30)),
        ),
        "chiconcuac",
    )
    following = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(10, 45)),
            business_datetime(local_date, time(11, 15)),
        ),
        "texcoco",
    )

    assert has_neighbor_separation_conflict(candidate, None, following)


def test_candidate_rejects_when_both_neighbors_lack_required_separation() -> None:
    local_date = date(2030, 6, 15)
    previous = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(9)),
            business_datetime(local_date, time(10)),
        ),
        "texcoco",
    )
    candidate = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(10, 15)),
            business_datetime(local_date, time(10, 45)),
        ),
        "chiconcuac",
    )
    following = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(11)),
            business_datetime(local_date, time(11, 30)),
        ),
        "texcoco",
    )

    assert has_neighbor_separation_conflict(candidate, previous, following)


def test_candidate_is_valid_when_it_respects_both_neighbor_separations() -> None:
    local_date = date(2030, 6, 15)
    previous = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(9)),
            business_datetime(local_date, time(10)),
        ),
        "texcoco",
    )
    candidate = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(10, 30)),
            business_datetime(local_date, time(11)),
        ),
        "chiconcuac",
    )
    following = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(11, 30)),
            business_datetime(local_date, time(12)),
        ),
        "texcoco",
    )

    assert not has_neighbor_separation_conflict(candidate, previous, following)


def test_cross_midnight_appointment_keeps_occupancy_and_same_branch_separation() -> None:
    start_date = date(2030, 6, 15)
    next_date = date(2030, 6, 16)
    start = business_datetime(start_date, time(19))
    overnight_appointment = ScheduledInterval(
        TimeInterval(start, appointment_end(start, timedelta(hours=5))),
        "chiconcuac",
    )
    overlapping_candidate = TimeInterval(
        business_datetime(start_date, time(23, 45)),
        business_datetime(next_date, time(0, 15)),
    )
    following_same_branch = ScheduledInterval(
        TimeInterval(
            business_datetime(next_date, time(0)),
            business_datetime(next_date, time(0, 30)),
        ),
        "chiconcuac",
    )

    assert overnight_appointment.interval.end == business_datetime(next_date, time(0))
    assert has_schedule_conflict(overlapping_candidate, (overnight_appointment.interval,))
    assert has_neighbor_separation_conflict(
        following_same_branch,
        overnight_appointment,
        None,
    )
    assert earliest_same_branch_start(overnight_appointment.interval) == business_datetime(
        next_date,
        time(0, 15),
    )


def test_cross_midnight_appointment_keeps_cross_branch_separation() -> None:
    start_date = date(2030, 6, 15)
    next_date = date(2030, 6, 16)
    start = business_datetime(start_date, time(19))
    overnight_appointment = ScheduledInterval(
        TimeInterval(start, appointment_end(start, timedelta(hours=5))),
        "texcoco",
    )
    following_other_branch = ScheduledInterval(
        TimeInterval(
            business_datetime(next_date, time(0, 15)),
            business_datetime(next_date, time(0, 45)),
        ),
        "chiconcuac",
    )

    assert has_neighbor_separation_conflict(
        following_other_branch,
        overnight_appointment,
        None,
    )
    assert earliest_cross_branch_start(overnight_appointment.interval) == business_datetime(
        next_date,
        time(0, 30),
    )


def test_scheduled_appointment_occupies_the_future_schedule() -> None:
    local_date = date(2030, 6, 15)
    scheduled = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(10)),
            business_datetime(local_date, time(11)),
        ),
        "chiconcuac",
    )
    candidate = TimeInterval(
        business_datetime(local_date, time(10, 30)),
        business_datetime(local_date, time(11, 30)),
    )

    assert has_schedule_conflict(candidate, occupying_intervals((scheduled,)))


@pytest.mark.parametrize(
    "final_status",
    ["cancelled", "completed", "no_show", "unrecorded_result"],
)
def test_final_appointment_states_do_not_occupy_the_future_schedule(
    final_status: str,
) -> None:
    local_date = date(2030, 6, 15)
    final_appointment = ScheduledInterval(
        TimeInterval(
            business_datetime(local_date, time(10)),
            business_datetime(local_date, time(11)),
        ),
        "chiconcuac",
        final_status,
    )
    candidate = TimeInterval(
        business_datetime(local_date, time(10, 30)),
        business_datetime(local_date, time(11, 30)),
    )

    assert not has_schedule_conflict(candidate, occupying_intervals((final_appointment,)))


def test_public_appointment_allows_exactly_sixty_minutes_notice() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10))

    validate_public_appointment_timing(
        current_time + timedelta(minutes=60),
        current_time,
    )


def test_public_appointment_rejects_one_second_less_than_sixty_minutes_notice() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10))

    with pytest.raises(InstantValidationError, match="at least 60 minutes"):
        validate_public_appointment_timing(
            current_time + timedelta(minutes=60) - timedelta(seconds=1),
            current_time,
        )


def test_public_appointment_allows_exactly_ninety_days() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10))

    validate_public_appointment_timing(
        current_time + timedelta(days=90),
        current_time,
    )


def test_public_appointment_rejects_one_second_after_ninety_days() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10))

    with pytest.raises(InstantValidationError, match="90-day horizon"):
        validate_public_appointment_timing(
            current_time + timedelta(days=90, seconds=1),
            current_time,
        )


def test_administrative_appointment_uses_the_current_grid_start_when_exact() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10, 15))

    assert earliest_administrative_start(current_time) == current_time


def test_administrative_appointment_uses_the_next_grid_start_when_needed() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10, 5))

    assert earliest_administrative_start(current_time) == business_datetime(
        date(2030, 6, 15),
        time(10, 15),
    )


def test_administrative_appointment_uses_the_next_day_after_last_start() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(19, 1))

    assert earliest_administrative_start(current_time) == business_datetime(
        date(2030, 6, 16),
        time(9),
    )


def test_administrative_appointment_allows_exactly_ninety_days() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10))

    validate_administrative_appointment_timing(
        current_time + timedelta(days=90),
        current_time,
    )


@pytest.mark.parametrize(
    ("requested_start", "error_message"),
    [
        (
            business_datetime(date(2030, 6, 15), time(10)),
            "cannot start in the past",
        ),
        (
            business_datetime(date(2030, 9, 13), time(10, 15, 1)),
            "90-day horizon",
        ),
        (
            business_datetime(date(2030, 6, 15), time(10, 20)),
            "approved daily grid",
        ),
    ],
)
def test_administrative_appointment_rejects_invalid_timing(
    requested_start: datetime,
    error_message: str,
) -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10, 15))

    with pytest.raises(InstantValidationError, match=error_message):
        validate_administrative_appointment_timing(requested_start, current_time)


def test_alternatives_return_the_three_nearest_available_starts() -> None:
    local_date = date(2030, 6, 15)
    requested_start = business_datetime(local_date, time(12))
    available_starts = (
        business_datetime(local_date, time(10)),
        business_datetime(local_date, time(11, 15)),
        requested_start,
        business_datetime(local_date, time(12, 30)),
        business_datetime(local_date, time(13, 15)),
        business_datetime(local_date, time(14)),
    )

    assert nearest_same_day_alternatives(requested_start, available_starts) == (
        business_datetime(local_date, time(12, 30)),
        business_datetime(local_date, time(11, 15)),
        business_datetime(local_date, time(13, 15)),
    )


def test_alternatives_exclude_available_starts_from_another_day() -> None:
    local_date = date(2030, 6, 15)
    requested_start = business_datetime(local_date, time(12))

    assert nearest_same_day_alternatives(
        requested_start,
        (
            business_datetime(local_date, time(11, 15)),
            business_datetime(date(2030, 6, 16), time(9)),
        ),
    ) == (business_datetime(local_date, time(11, 15)),)


def test_alternatives_prioritize_the_later_start_when_distances_tie() -> None:
    local_date = date(2030, 6, 15)
    requested_start = business_datetime(local_date, time(12))

    assert nearest_same_day_alternatives(
        requested_start,
        (
            business_datetime(local_date, time(11, 45)),
            business_datetime(local_date, time(12, 15)),
        ),
    ) == (
        business_datetime(local_date, time(12, 15)),
        business_datetime(local_date, time(11, 45)),
    )


def test_alternative_suggestion_requires_another_date_when_none_exist() -> None:
    requested_start = business_datetime(date(2030, 6, 15), time(12))

    assert same_day_alternative_suggestion(
        requested_start,
        (),
    ).requires_different_date


@pytest.mark.parametrize(
    ("requested_start", "current_time", "error_message"),
    [
        (
            business_datetime(date(2030, 6, 15), time(8, 45)),
            business_datetime(date(2030, 6, 14), time(8)),
            "during business hours",
        ),
        (
            business_datetime(date(2030, 6, 15), time(10, 7)),
            business_datetime(date(2030, 6, 15), time(8)),
            "approved daily grid",
        ),
        (
            business_datetime(date(2030, 6, 15), time(10, 45)),
            business_datetime(date(2030, 6, 15), time(10)),
            "at least 60 minutes",
        ),
        (
            business_datetime(date(2030, 9, 13), time(10, 15)),
            business_datetime(date(2030, 6, 15), time(10)),
            "90-day horizon",
        ),
    ],
)
def test_public_invalid_timing_does_not_propose_alternatives(
    requested_start: datetime,
    current_time: datetime,
    error_message: str,
) -> None:
    available_starts = (business_datetime(date(2030, 6, 15), time(11, 15)),)

    with pytest.raises(InstantValidationError, match=error_message):
        public_same_day_alternative_suggestion(
            requested_start,
            current_time,
            available_starts,
        )


def test_invalid_start_format_does_not_propose_alternatives() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10))
    available_starts = (business_datetime(date(2030, 6, 15), time(11, 15)),)

    with pytest.raises(InstantValidationError, match="must be a datetime"):
        public_same_day_alternative_suggestion(
            "2030-06-15 11:00",
            current_time,
            available_starts,
        )  # type: ignore[arg-type]


def test_administrative_invalid_timing_does_not_propose_alternatives() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10, 15))
    available_starts = (business_datetime(date(2030, 6, 15), time(10, 30)),)

    with pytest.raises(InstantValidationError, match="cannot start in the past"):
        administrative_same_day_alternative_suggestion(
            business_datetime(date(2030, 6, 15), time(10)),
            current_time,
            available_starts,
        )


def test_valid_but_unavailable_public_timing_proposes_alternatives() -> None:
    current_time = business_datetime(date(2030, 6, 15), time(10))
    requested_start = business_datetime(date(2030, 6, 15), time(11))
    available_start = business_datetime(date(2030, 6, 15), time(11, 15))

    assert public_same_day_alternative_suggestion(
        requested_start,
        current_time,
        (available_start,),
    ).starts == (available_start,)
