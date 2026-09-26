"""T067 unit evidence for preparing a factor without consuming its proof."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.app.application.admin_access.prepare_totp_replacement import (
    PrepareAdministrativeTotpReplacement,
    TotpReplacementCandidate,
)
from backend.app.application.clock import FixedClock


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
RECOVERY_DIGEST = b"r" * 32


class Store:
    def __init__(self, *, save_succeeds=True):
        self.candidate = TotpReplacementCandidate(
            account_id=7,
            password_hash="stored hash",
            factor_id=3,
            factor_ciphertext=b"old ciphertext",
            factor_key_version="v1",
            factor_algorithm="SHA1",
            used_period_counters=(40,),
            active_recovery_digests=(RECOVERY_DIGEST,),
        )
        self.save_succeeds = save_succeeds
        self.saved = []

    def load_candidate(self, *, account_id):
        assert account_id == 7
        return self.candidate

    def save_pending_setup(self, **kwargs):
        self.saved.append(kwargs)
        return self.save_succeeds


class Harness:
    def __init__(self, *, password_ok=True, factor_ok=True, allowed=True, save_succeeds=True):
        self.store = Store(save_succeeds=save_succeeds)
        self.failures = []
        self.audit = []
        self.operation = PrepareAdministrativeTotpReplacement(
            store=self.store,
            credential_guard=SimpleNamespace(ensure_allowed=lambda **_: allowed),
            failure_recorder=SimpleNamespace(record=lambda **kwargs: self.failures.append(kwargs)),
            password_hasher=SimpleNamespace(
                verify_and_upgrade=lambda **_: SimpleNamespace(verified=password_ok)
            ),
            factor_protector=SimpleNamespace(
                key_version="v1", decrypt=lambda **_: b"OLDSECRET"
            ),
            pending_factor_protector=SimpleNamespace(
                key_version="v1",
                encrypt=lambda **kwargs: b"encrypted:" + kwargs["secret"],
            ),
            totp=SimpleNamespace(
                verify=lambda **kwargs: 42 if factor_ok and kwargs["code"] == "123456" else None,
                generate_secret=lambda: b"NEWSECRET",
                provisioning_uri=lambda **kwargs: f"otpauth://totp/{kwargs['secret'].decode()}",
            ),
            recovery_codes=SimpleNamespace(
                match=lambda **kwargs: RECOVERY_DIGEST
                if factor_ok and kwargs["value"] == "valid recovery code"
                else None
            ),
            audit=SimpleNamespace(record=lambda **kwargs: self.audit.append(kwargs)),
            clock=FixedClock(NOW),
        )

    def prepare(self, *, code="123456", recovery=None, password="current phrase"):
        return self.operation.prepare(
            account_id=7,
            current_password=password,
            totp_code=code if recovery is None else None,
            recovery_code=recovery,
        )


def test_t067_totp_prepares_new_secret_and_retains_unconsumed_period_reference():
    harness = Harness()

    result = harness.prepare()

    assert result.provisioning_uri == "otpauth://totp/NEWSECRET"
    assert result.manual_key == "NEWSECRET"
    assert len(harness.store.saved) == 1
    saved = harness.store.saved[0]
    assert saved["setup"].flow == "totp_replacement"
    assert saved["setup"].totp_secret_ciphertext == b"encrypted:NEWSECRET"
    assert saved["setup"].expires_at - saved["setup"].created_at == timedelta(minutes=30)
    assert saved["verified_totp_period_counter"] == 42
    assert saved["verified_totp_factor_id"] == 3
    assert saved["verified_recovery_code_digest"] is None
    assert harness.failures == []
    assert harness.audit == []


def test_t067_recovery_code_prepares_without_consuming_its_digest():
    harness = Harness()

    result = harness.prepare(recovery="valid recovery code")

    assert result.manual_key == "NEWSECRET"
    assert harness.store.saved[0]["verified_totp_period_counter"] is None
    assert harness.store.saved[0]["verified_totp_factor_id"] is None
    assert harness.store.saved[0]["verified_recovery_code_digest"] == RECOVERY_DIGEST
    assert harness.failures == []


@pytest.mark.parametrize(
    ("password", "code"),
    [("incorrect", "123456"), ("current phrase", "000000")],
)
def test_t067_invalid_totp_rejects_once_without_saving_new_setup(password, code):
    harness = Harness(password_ok=password == "current phrase", factor_ok=code == "123456")

    result = harness.prepare(password=password, code=code)

    assert result == "invalid_credentials"
    assert harness.store.saved == []
    assert harness.failures == [{"account_id": 7, "operation": "totp_replacement"}]
    assert harness.audit == [{"actor_account_id": 7, "action": "totp_replacement", "result": "failed"}]


def test_t067_store_failure_does_not_return_setup_or_count_a_credential_failure():
    harness = Harness(save_succeeds=False)

    result = harness.prepare()

    assert result == "unavailable"
    assert len(harness.store.saved) == 1
    assert harness.failures == []
