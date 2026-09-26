"""T066 unit evidence for authenticated recovery-code regeneration."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.application.admin_access.regenerate_recovery_codes import (
    RegenerateAdministrativeRecoveryCodes,
    RecoveryCodeRegenerationCandidate,
)
from backend.app.application.clock import FixedClock


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
NEW_CODES = tuple(
    f"ABCD-EFGH-JKLM-NPQ{digit}" for digit in "23456789AB"
)


class Store:
    def __init__(self, *, replace_succeeds: bool = True) -> None:
        self.candidate = RecoveryCodeRegenerationCandidate(
            account_id=7,
            password_hash="stored hash",
            factor_id=3,
            factor_ciphertext=b"encrypted factor",
            factor_key_version="v1",
            factor_algorithm="SHA1",
            used_period_counters=(),
            current_email="synthetic.owner@example.test",
        )
        self.replace_succeeds = replace_succeeds
        self.replacements = []

    def load_candidate(self, *, account_id):
        assert account_id == 7
        return self.candidate

    def replace_codes(self, **kwargs):
        self.replacements.append(kwargs)
        return self.replace_succeeds


class Harness:
    def __init__(self, *, allowed=True, replace_succeeds=True) -> None:
        self.store = Store(replace_succeeds=replace_succeeds)
        self.failures = []
        self.audit = []
        self.notifications = []
        self.invalidations = []
        self.allowed = allowed
        self.operation = RegenerateAdministrativeRecoveryCodes(
            store=self.store,
            credential_guard=SimpleNamespace(
                ensure_allowed=lambda **_: self.allowed
            ),
            failure_recorder=SimpleNamespace(
                record=lambda **kwargs: self.failures.append(kwargs)
            ),
            password_hasher=SimpleNamespace(
                verify_and_upgrade=lambda **kwargs: SimpleNamespace(
                    verified=kwargs["password"] == "current phrase"
                )
            ),
            factor_protector=SimpleNamespace(
                key_version="v1", decrypt=lambda **_: b"factor secret"
            ),
            totp=SimpleNamespace(
                verify=lambda **kwargs: 42 if kwargs["code"] == "123456" else None
            ),
            recovery_codes=SimpleNamespace(
                key_version="v1",
                generate=lambda: tuple(
                    SimpleNamespace(
                        display_value=value,
                        lookup_digest=bytes([index]) * 32,
                    )
                    for index, value in enumerate(NEW_CODES, start=1)
                ),
            ),
            invalidator=SimpleNamespace(
                execute=lambda **kwargs: self.invalidations.append(kwargs)
            ),
            audit=SimpleNamespace(record=lambda **kwargs: self.audit.append(kwargs)),
            notifications=SimpleNamespace(record=self._record_notice),
            clock=FixedClock(NOW),
        )

    def regenerate(self, *, password="current phrase", code="123456"):
        return self.operation.regenerate(
            account_id=7,
            current_password=password,
            totp_code=code,
        )

    def _record_notice(self, **kwargs):
        self.notifications.append(kwargs)
        return SimpleNamespace(delivery_id=9)


def test_t066_success_replaces_ten_codes_and_records_security_effects() -> None:
    harness = Harness()

    result = harness.regenerate()

    assert result.status == "regenerated"
    assert result.recovery_codes == NEW_CODES
    assert len(harness.store.replacements) == 1
    replacement = harness.store.replacements[0]
    assert replacement["period_counter"] == 42
    assert len(replacement["recovery_codes"]) == 10
    assert all(code.status == "active" for code in replacement["recovery_codes"])
    assert [code.position for code in replacement["recovery_codes"]] == list(range(1, 11))
    assert harness.invalidations == [{"account_id": 7}]
    assert harness.audit == [
        {
            "actor_account_id": 7,
            "action": "recovery_code_regeneration",
            "result": "succeeded",
        }
    ]
    assert harness.notifications == [
        {
            "event": "recovery_codes_changed",
            "template": "recovery_codes_changed_notice",
            "recipient": "synthetic.owner@example.test",
            "idempotency_reference": "recovery_codes:7:3:42",
        }
    ]
    assert harness.failures == []


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("incorrect phrase", "123456"),
        ("current phrase", "000000"),
        ("incorrect phrase", "000000"),
    ],
)
def test_t066_invalid_credentials_count_once_and_keep_old_batch(
    password: str, code: str
) -> None:
    harness = Harness()

    result = harness.regenerate(password=password, code=code)

    assert result.status == "invalid_credentials"
    assert harness.failures == [
        {"account_id": 7, "operation": "recovery_code_regeneration"}
    ]
    assert harness.store.replacements == []
    assert harness.invalidations == []
    assert harness.notifications == []
    assert harness.audit == [
        {
            "actor_account_id": 7,
            "action": "recovery_code_regeneration",
            "result": "failed",
        }
    ]


def test_t066_replayed_totp_counts_one_failure_without_replacing_codes() -> None:
    harness = Harness(replace_succeeds=False)

    result = harness.regenerate()

    assert result.status == "invalid_credentials"
    assert harness.failures == [
        {"account_id": 7, "operation": "recovery_code_regeneration"}
    ]
    assert len(harness.store.replacements) == 1
    assert harness.invalidations == []
    assert harness.notifications == []


def test_t066_existing_lock_rejects_without_counting_again() -> None:
    harness = Harness(allowed=False)

    result = harness.regenerate()

    assert result.status == "invalid_credentials"
    assert harness.failures == []
    assert harness.store.replacements == []
    assert harness.audit[0]["result"] == "failed"
