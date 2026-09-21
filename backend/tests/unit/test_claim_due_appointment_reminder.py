"""T093E unit evidence for due-reminder claim decisions."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator

import pytest

from backend.app.application.claim_due_appointment_reminder import (
    ClaimedDueReminder,
    ClaimDueAppointmentReminder,
    DueAppointmentReminderClaimRepository,
    ReminderClaimConfigurationError,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.time import BUSINESS_TIME_ZONE, normalize_instant


NOW = datetime(2030, 6, 15, 10, tzinfo=BUSINESS_TIME_ZONE)
CLAIM_LEASE = timedelta(minutes=5)


class FakeReminderClaimRepository:
    def __init__(self, scheduled_start: datetime | None) -> None:
        self.scheduled_start = scheduled_start
        self.claim_calls: list[dict[str, datetime]] = []
        self.omit_calls: list[dict[str, object]] = []

    def claim_next_due_reminder(
        self,
        *,
        claimed_at: datetime,
        claim_expires_at: datetime,
    ) -> ClaimedDueReminder | None:
        self.claim_calls.append(
            {
                "claimed_at": claimed_at,
                "claim_expires_at": claim_expires_at,
            }
        )
        if self.scheduled_start is None:
            return None
        return ClaimedDueReminder(
            reminder_id=17,
            appointment_id=29,
            appointment_scheduled_start=self.scheduled_start,
        )

    def omit_claimed_reminder(self, **values: object) -> bool:
        self.omit_calls.append(values)
        return True


class FakeReminderClaimUnitOfWork:
    def __init__(self, repository: FakeReminderClaimRepository) -> None:
        self.repository = repository

    @contextmanager
    def transaction(self) -> Iterator[DueAppointmentReminderClaimRepository]:
        yield self.repository


@pytest.mark.parametrize(
    ("remaining", "expected_outcome"),
    (
        pytest.param(timedelta(minutes=60, seconds=1), "claimed", id="over-60"),
        pytest.param(timedelta(minutes=60), "omitted", id="exactly-60"),
        pytest.param(timedelta(minutes=59, seconds=59), "omitted", id="under-60"),
    ),
)
def test_t093e_applies_the_exact_sixty_minute_processing_boundary(
    remaining: timedelta,
    expected_outcome: str,
) -> None:
    repository = FakeReminderClaimRepository(NOW + remaining)

    result = _claimer(repository).execute()

    assert result is not None
    assert result.outcome == expected_outcome
    if expected_outcome == "claimed":
        assert result.claimed_at == normalize_instant(NOW)
        assert result.claim_expires_at == normalize_instant(NOW) + CLAIM_LEASE
        assert repository.omit_calls == []
    else:
        assert result.claimed_at is None
        assert result.claim_expires_at is None
        assert repository.omit_calls == [
            {
                "reminder_id": 17,
                "claimed_at": normalize_instant(NOW),
                "status_changed_at": normalize_instant(NOW),
            }
        ]


def test_t093e_returns_none_when_no_due_reminder_can_be_claimed() -> None:
    repository = FakeReminderClaimRepository(None)

    assert _claimer(repository).execute() is None
    assert repository.omit_calls == []


@pytest.mark.parametrize("claim_lease", (timedelta(), timedelta(seconds=-1)))
def test_t093e_rejects_a_nonpositive_internal_claim_lease(
    claim_lease: timedelta,
) -> None:
    repository = FakeReminderClaimRepository(NOW + timedelta(hours=2))

    with pytest.raises(ReminderClaimConfigurationError):
        ClaimDueAppointmentReminder(
            unit_of_work=FakeReminderClaimUnitOfWork(repository),
            clock=FixedClock(NOW),
            claim_lease=claim_lease,
        )


def _claimer(
    repository: FakeReminderClaimRepository,
) -> ClaimDueAppointmentReminder:
    return ClaimDueAppointmentReminder(
        unit_of_work=FakeReminderClaimUnitOfWork(repository),
        clock=FixedClock(NOW),
        claim_lease=CLAIM_LEASE,
    )
