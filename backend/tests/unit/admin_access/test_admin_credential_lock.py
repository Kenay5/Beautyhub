"""T045 unit evidence for effects created by the fifth credential failure."""

from datetime import datetime, timedelta, timezone

from backend.app.application.admin_access.account_security import (
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.domain.authentication.account_security import (
    AdministrativeCredentialFailureResult,
)


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)


class FailureRecorder:
    def __init__(self, outcome: AdministrativeCredentialFailureResult) -> None:
        self.outcome = outcome
        self.calls = []

    def record(self, *, account_id, operation):
        self.calls.append((account_id, operation))
        return self.outcome


class AuditRecorder:
    def __init__(self) -> None:
        self.events = []

    def record(self, **event) -> None:
        self.events.append(event)


class NotificationRecorder:
    def __init__(self) -> None:
        self.intents = []

    def record(self, **intent):
        self.intents.append(intent)


class Recipients:
    def lock_notification_recipients(self, *, account_id):
        assert account_id == 7
        return ("synthetic.staff@example.test", "synthetic.owner@example.test")


def _protected(outcome: AdministrativeCredentialFailureResult):
    audit = AuditRecorder()
    notifications = NotificationRecorder()
    recorder = RecordProtectedAdministrativeCredentialFailure(
        failure_recorder=FailureRecorder(outcome),
        audit=audit,
        notifications=notifications,
        recipients=Recipients(),
    )
    return recorder, audit, notifications


def test_t045_fifth_failure_audits_and_prepares_staff_and_owner_notices() -> None:
    recorder, audit, notifications = _protected(
        AdministrativeCredentialFailureResult(
            failure_count=5,
            lock_until=NOW + timedelta(minutes=15),
            blocked=False,
            failure_event_id=41,
        )
    )

    result = recorder.record(account_id=7, operation="login")

    assert result.started_lock
    assert audit.events == [
        {
            "actor_account_id": 7,
            "action": "account_locked",
            "result": "succeeded",
            "target_reference": "admin_account:7",
        }
    ]
    assert notifications.intents == [
        {
            "event": "account_locked",
            "template": "account_locked_notice",
            "recipient": "synthetic.staff@example.test",
            "idempotency_reference": "credential_failure:41",
        },
        {
            "event": "account_locked",
            "template": "account_locked_notice",
            "recipient": "synthetic.owner@example.test",
            "idempotency_reference": "credential_failure:41",
        },
    ]


def test_t045_failure_before_threshold_has_no_lock_side_effects() -> None:
    recorder, audit, notifications = _protected(
        AdministrativeCredentialFailureResult(
            failure_count=4,
            lock_until=None,
            blocked=False,
            failure_event_id=40,
        )
    )

    result = recorder.record(account_id=7, operation="login")

    assert not result.started_lock
    assert audit.events == []
    assert notifications.intents == []


def test_t045_request_finding_an_existing_lock_does_not_duplicate_effects() -> None:
    recorder, audit, notifications = _protected(
        AdministrativeCredentialFailureResult(
            failure_count=5,
            lock_until=NOW + timedelta(minutes=15),
            blocked=True,
        )
    )

    result = recorder.record(account_id=7, operation="login")

    assert not result.started_lock
    assert audit.events == []
    assert notifications.intents == []
