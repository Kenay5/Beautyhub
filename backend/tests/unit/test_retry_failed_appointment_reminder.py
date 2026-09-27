"""T093G unit evidence for bounded administrative reminder retries."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.retry_failed_appointment_reminder import (
    AdministrativeAppointmentNotificationRateLimitError,
    AdministrativeReminderRetryActor,
    AdministrativeReminderRetryNotAuthorizedError,
    AppointmentReminderRetryNotPermittedError,
    AppointmentReminderRetryRepository,
    LockedReminderRetry,
    RetryFailedAppointmentReminder,
)
from backend.app.domain.notification_delivery import FAILED_DELIVERY_STATUS
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator


NOW = datetime(2030, 6, 15, 12, tzinfo=BUSINESS_TIME_ZONE)


class RecordingLimiter:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.account_ids: list[int] = []

    def ensure_allowed(self, *, account_id: int) -> None:
        self.account_ids.append(account_id)
        if not self.allowed:
            raise AdministrativeAppointmentNotificationRateLimitError(
                "synthetic rate limit"
            )


class FakeReminderRetryRepository:
    def __init__(self, context: LockedReminderRetry) -> None:
        self.context = context
        self.locked_delivery_ids: list[int] = []
        self.created: list[dict[str, object]] = []

    def lock_retry_context(self, *, delivery_id: int) -> LockedReminderRetry | None:
        self.locked_delivery_ids.append(delivery_id)
        return self.context if delivery_id == self.context.delivery_id else None

    def create_pending_retry(self, **values: object) -> int:
        self.created.append(values)
        return 47


class FakeReminderRetryUnitOfWork:
    def __init__(self, repository: FakeReminderRetryRepository) -> None:
        self.repository = repository

    @contextmanager
    def transaction(self) -> Iterator[AppointmentReminderRetryRepository]:
        yield self.repository


class RecordingResultWriter:
    def __init__(self) -> None:
        self.results: list[dict[str, object]] = []

    def record_result(self, **values: object) -> None:
        self.results.append(values)


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, **event: object) -> None:
        self.events.append(event)


@pytest.mark.parametrize("role", ("owner", "staff"))
def test_t093g_allows_an_authorized_owner_or_staff_once_and_uses_current_contact(
    role: str,
) -> None:
    limiter = RecordingLimiter()
    repository = FakeReminderRetryRepository(_context())
    email = EmailSimulator(outcome="accepted")
    whatsapp = WhatsAppSimulator(outcome="accepted")

    result = _service(
        repository=repository,
        limiter=limiter,
        email=email,
        whatsapp=whatsapp,
    ).execute(actor=_actor(role), delivery_id=31)

    assert result.delivery_id == 47
    assert result.previous_delivery_id == 31
    assert result.channel == "email"
    assert result.status == "accepted"
    assert limiter.account_ids == [7]
    assert repository.created == [
        {
            "appointment_id": 29,
            "event": "appointment_reminder",
            "channel": "email",
            "previous_delivery_id": 31,
            "status_changed_at": NOW,
        }
    ]
    assert [notification.recipient for notification in email.notifications] == [
        "updated-contact@example.test"
    ]
    assert whatsapp.notifications == ()


def test_t094_boundary_represents_an_unauthenticated_request() -> None:
    limiter = RecordingLimiter()
    repository = FakeReminderRetryRepository(_context())

    with pytest.raises(AdministrativeReminderRetryNotAuthorizedError):
        _service(
            repository=repository,
            limiter=limiter,
        ).execute(actor=None, delivery_id=31)  # type: ignore[arg-type]

    assert limiter.account_ids == []
    assert repository.locked_delivery_ids == []
    assert repository.created == []


def test_t093g_rate_limit_is_consumed_once_before_retry_data_is_accessed() -> None:
    limiter = RecordingLimiter(allowed=False)
    repository = FakeReminderRetryRepository(_context())

    with pytest.raises(AdministrativeAppointmentNotificationRateLimitError):
        _service(
            repository=repository,
            limiter=limiter,
        ).execute(actor=_actor("owner"), delivery_id=31)

    assert limiter.account_ids == [7]
    assert repository.locked_delivery_ids == []
    assert repository.created == []


@pytest.mark.parametrize(
    ("context_factory", "case"),
    (
        pytest.param(
            lambda: _context(
                appointment_start=NOW + timedelta(minutes=60, seconds=1)
            ),
            "over-sixty",
            id="over-sixty",
        ),
        pytest.param(
            lambda: _context(appointment_start=NOW + timedelta(minutes=60)),
            "exactly-sixty",
            id="exactly-sixty",
        ),
        pytest.param(
            lambda: _context(retry_count=3),
            "three-retries",
            id="three-retries",
        ),
        pytest.param(
            lambda: _context(
                last_retry_started_at=NOW - timedelta(minutes=4, seconds=59)
            ),
            "too-soon",
            id="too-soon",
        ),
        pytest.param(
            lambda: _context(has_later_attempt=True),
            "superseded-failure",
            id="superseded-failure",
        ),
    ),
)
def test_t093g_enforces_time_channel_chain_and_retry_bounds(
    context_factory,
    case: str,
) -> None:
    context = context_factory()
    repository = FakeReminderRetryRepository(context)
    service = _service(repository=repository)

    if case == "over-sixty":
        service.execute(actor=_actor("owner"), delivery_id=31)
        assert repository.created
    else:
        with pytest.raises(AppointmentReminderRetryNotPermittedError):
            service.execute(actor=_actor("owner"), delivery_id=31)
        assert repository.created == []


def test_t093g_accepts_the_exact_five_minute_retry_separation() -> None:
    repository = FakeReminderRetryRepository(
        _context(last_retry_started_at=NOW - timedelta(minutes=5))
    )

    _service(repository=repository).execute(actor=_actor("owner"), delivery_id=31)

    assert repository.created


def _service(
    *,
    repository: FakeReminderRetryRepository,
    limiter: RecordingLimiter | None = None,
    email: EmailSimulator | None = None,
    whatsapp: WhatsAppSimulator | None = None,
) -> RetryFailedAppointmentReminder:
    return RetryFailedAppointmentReminder(
        limiter=limiter or RecordingLimiter(),
        unit_of_work=FakeReminderRetryUnitOfWork(repository),
        dispatcher=NotificationDispatcher(
            email_port=email or EmailSimulator(outcome="accepted"),
            whatsapp_port=whatsapp or WhatsAppSimulator(outcome="accepted"),
            result_writer=RecordingResultWriter(),
        ),
        clock=FixedClock(NOW),
        audit=RecordingAudit(),
    )


def _actor(role: str) -> AdministrativeReminderRetryActor:
    return AdministrativeReminderRetryActor(account_id=7, role=role)  # type: ignore[arg-type]


def _context(
    *,
    appointment_start: datetime | None = None,
    retry_count: int = 0,
    last_retry_started_at: datetime | None = None,
    has_later_attempt: bool = False,
) -> LockedReminderRetry:
    scheduled_start = appointment_start or NOW + timedelta(hours=2)
    return LockedReminderRetry(
        delivery_id=31,
        appointment_id=29,
        reminder_id=17,
        event="appointment_reminder",
        channel="email",
        delivery_status=FAILED_DELIVERY_STATUS,
        appointment_status="scheduled",
        appointment_scheduled_start=scheduled_start,
        reminder_scheduled_start=scheduled_start,
        reminder_status="completed",
        retry_count=retry_count,
        last_retry_started_at=last_retry_started_at,
        has_later_attempt=has_later_attempt,
        email="updated-contact@example.test",
        phone="5510000000",
        service_name="Servicio sintético",
        duration_minutes=60,
        price=Decimal("350.00"),
        branch="chiconcuac",
    )
