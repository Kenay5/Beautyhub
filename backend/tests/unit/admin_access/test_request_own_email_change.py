"""T072 unit evidence for authenticated own-email reservation decisions."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.application.admin_access.request_own_email_change import (
    OwnEmailChangeCandidate,
    RequestOwnAdministrativeEmailChange,
)
from backend.app.application.clock import FixedClock


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)


class Harness:
    def __init__(self, *, password_ok=True, period=42, allowed=True, reserve=True):
        self.candidate = OwnEmailChangeCandidate(
            account_id=7,
            password_hash="stored hash",
            factor_id=3,
            factor_ciphertext=b"encrypted factor",
            factor_key_version="v1",
            factor_algorithm="SHA1",
            used_period_counters=(),
        )
        self.reservations = []
        self.failures = []
        self.audits = []
        self.operation = RequestOwnAdministrativeEmailChange(
            store=SimpleNamespace(
                load_candidate=lambda **_: self.candidate,
                reserve_email=self._reserve,
            ),
            email_protector=SimpleNamespace(protect=lambda value: {"email": value}),
            credential_guard=SimpleNamespace(ensure_allowed=lambda **_: allowed),
            failure_recorder=SimpleNamespace(
                record=lambda **kwargs: self.failures.append(kwargs)
            ),
            password_hasher=SimpleNamespace(
                verify_and_upgrade=lambda **_: SimpleNamespace(verified=password_ok)
            ),
            factor_protector=SimpleNamespace(
                key_version="v1", decrypt=lambda **_: b"factor secret"
            ),
            totp=SimpleNamespace(verify=lambda **_: period),
            audit=SimpleNamespace(record=lambda **kwargs: self.audits.append(kwargs)),
            clock=FixedClock(NOW),
        )
        self.reserve_result = reserve

    def _reserve(self, **kwargs):
        self.reservations.append(kwargs)
        return self.reserve_result

    def request(self, *, email=" New.Address@Example.test ", password="good", code="123456"):
        return self.operation.request(
            account_id=7,
            new_email=email,
            current_password=password,
            totp_code=code,
        )


def test_t072_valid_credentials_reserve_only_the_current_actor_address():
    harness = Harness()

    assert harness.request() == "reserved"
    assert harness.reservations[0]["candidate"].account_id == 7
    assert harness.reservations[0]["email"] == {"email": " New.Address@Example.test "}
    assert harness.reservations[0]["period_counter"] == 42
    assert harness.audits[-1]["result"] == "succeeded"
    assert harness.failures == []


@pytest.mark.parametrize(
    ("password_ok", "period"),
    [(False, 42), (True, None), (False, None)],
)
def test_t072_invalid_credentials_count_once_and_do_not_reserve(password_ok, period):
    harness = Harness(password_ok=password_ok, period=period)

    assert harness.request() == "invalid_credentials"
    assert harness.reservations == []
    assert harness.failures == [{"account_id": 7, "operation": "email_change"}]
    assert harness.audits[-1]["result"] == "failed"


def test_t072_occupied_or_unreservable_address_preserves_credentials_and_totp():
    harness = Harness(reserve=False)

    assert harness.request() == "unavailable"
    assert len(harness.reservations) == 1
    assert harness.failures == []
    assert harness.audits[-1]["result"] == "failed"


def test_t072_invalid_address_is_rejected_before_credential_side_effects():
    harness = Harness()
    harness.operation._email_protector = SimpleNamespace(
        protect=lambda _: (_ for _ in ()).throw(ValueError("invalid"))
    )

    assert harness.request(email="not-an-email") == "invalid_email"
    assert harness.reservations == []
    assert harness.failures == []
