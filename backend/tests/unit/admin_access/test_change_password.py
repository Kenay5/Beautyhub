"""T057 evidence for authenticated password-change decisions."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.application.admin_access.change_password import (
    ChangeAdministrativePassword,
    PasswordChangeCandidate,
)
from backend.app.application.clock import FixedClock


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)


class Store:
    def __init__(self) -> None:
        self.candidate = PasswordChangeCandidate(
            account_id=7,
            password_hash="stored hash",
            factor_id=3,
            factor_ciphertext=b"encrypted factor",
            factor_key_version="v1",
            factor_algorithm="SHA1",
            used_period_counters=(),
            current_email="synthetic.owner@example.test",
        )
        self.replacements = []

    def load_candidate(self, *, account_id):
        assert account_id == 7
        return self.candidate

    def replace_password(self, **kwargs):
        self.replacements.append(kwargs)
        return True


class Harness:
    def __init__(self, *, allowed=True, blocked=False) -> None:
        self.store = Store()
        self.failures = []
        self.audit = []
        self.notifications = []
        self.invalidations = []
        self.blocked = blocked
        self.operation = ChangeAdministrativePassword(
            store=self.store,
            credential_guard=SimpleNamespace(ensure_allowed=lambda **_: allowed),
            failure_recorder=SimpleNamespace(record=lambda **kwargs: self.failures.append(kwargs)),
            password_hasher=SimpleNamespace(
                verify_and_upgrade=lambda **kwargs: SimpleNamespace(
                    verified=kwargs["password"] == "current phrase"
                ),
                hash_password=lambda value: f"hash of {value}",
            ),
            factor_protector=SimpleNamespace(
                key_version="v1", decrypt=lambda **_: b"factor secret"
            ),
            totp=SimpleNamespace(
                verify=lambda **kwargs: 42 if kwargs["code"] == "123456" else None
            ),
            blocked_passwords=SimpleNamespace(contains=lambda _: self.blocked),
            invalidator=SimpleNamespace(execute=lambda **kwargs: self.invalidations.append(kwargs)),
            audit=SimpleNamespace(record=lambda **kwargs: self.audit.append(kwargs)),
            notifications=SimpleNamespace(record=self._record_notice),
            clock=FixedClock(NOW),
        )

    def change(self, *, current="current phrase", code="123456", new="fresh long phrase"):
        return self.operation.change(
            account_id=7,
            current_password=current,
            totp_code=code,
            new_password=new,
        )

    def _record_notice(self, **kwargs):
        self.notifications.append(kwargs)
        return SimpleNamespace(delivery_id=9)


def test_t057_success_changes_only_after_complete_validation_and_records_notice() -> None:
    harness = Harness()

    assert harness.change().status == "changed"

    assert len(harness.store.replacements) == 1
    assert harness.store.replacements[0]["period_counter"] == 42
    assert harness.invalidations == [{"account_id": 7}]
    assert harness.audit == [
        {"actor_account_id": 7, "action": "password_change", "result": "succeeded"}
    ]
    assert harness.notifications == [
        {
            "event": "password_changed",
            "template": "password_changed_notice",
            "recipient": "synthetic.owner@example.test",
            "idempotency_reference": "password_change:7:3:42",
        }
    ]
    assert harness.failures == []


@pytest.mark.parametrize(
    ("current", "code"),
    [("wrong phrase", "123456"), ("current phrase", "000000"), ("wrong phrase", "000000")],
)
def test_t057_one_failed_request_counts_once_and_preserves_credentials(current, code) -> None:
    harness = Harness()

    assert harness.change(current=current, code=code).status == "invalid_credentials"

    assert harness.failures == [{"account_id": 7, "operation": "password_change"}]
    assert harness.store.replacements == []
    assert harness.invalidations == []
    assert harness.notifications == []
    assert harness.audit[0]["result"] == "failed"


def test_t057_invalid_new_password_does_not_consume_a_valid_factor() -> None:
    harness = Harness()

    assert harness.change(new="short").status == "invalid_password"
    assert harness.store.replacements == []
    assert harness.invalidations == []
    assert harness.failures == []


def test_t057_blocked_password_is_rejected_without_changing_current_credentials() -> None:
    harness = Harness(blocked=True)
    assert harness.change().status == "invalid_password"
    assert harness.store.replacements == []
    assert harness.failures == []


def test_t057_existing_lock_rejects_before_loading_or_counting_credentials() -> None:
    harness = Harness(allowed=False)
    harness.store.load_candidate = lambda **_: pytest.fail("candidate should not load")

    assert harness.change().status == "invalid_credentials"
    assert harness.failures == []
    assert harness.store.replacements == []
