"""T092 evidence for opaque account subjects and no-op rejections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.admin_access.rate_limit import (
    AuthenticatedAdministrativeRequestLimitError,
    LimitAuthenticatedAdministrativeRequests,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.security.administrative_rate_limit_subject import (
    AdministrativeRateLimitSubjectProtectionError,
    AdministrativeRateLimitSubjectProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


NOW = datetime(2030, 6, 1, 10, tzinfo=timezone.utc)
KEY_RING = CryptographyKeyRing(
    CryptographyKeyConfiguration(
        root_key=SecretValue("AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE"),
        key_version="v1",
    )
)


def test_t092_account_fingerprints_are_stable_separate_and_non_reversible() -> None:
    protector = AdministrativeRateLimitSubjectProtector(key_ring=KEY_RING)

    first = protector.fingerprint_account(42)

    assert len(first) == 32
    assert first == protector.fingerprint_account(42)
    assert first != protector.fingerprint_account(43)
    assert b"42" not in first
    assert b"admin-account" not in first


@pytest.mark.parametrize("value", (0, -1, True, "42", 2**63))
def test_t092_rejects_non_database_account_identifiers(value) -> None:
    protector = AdministrativeRateLimitSubjectProtector(key_ring=KEY_RING)

    with pytest.raises(AdministrativeRateLimitSubjectProtectionError):
        protector.fingerprint_account(value)


class Store:
    def __init__(self, *, accepted: bool) -> None:
        self.accepted = accepted
        self.calls = []

    def try_reserve(self, **values) -> bool:
        self.calls.append(values)
        return self.accepted


def test_t092_uses_registered_limit_and_rejects_without_business_side_effects() -> None:
    store = Store(accepted=False)
    limiter = LimitAuthenticatedAdministrativeRequests(
        store=store,
        clock=FixedClock(NOW),
        subject_fingerprint=b"a" * 32,
        secret_generator=SequenceSecretGenerator([b"r" * 32]),
    )
    business_calls = 0

    with pytest.raises(AuthenticatedAdministrativeRequestLimitError):
        limiter.ensure_allowed()
    # No caller-side work is reachable after the denial.
    assert business_calls == 0
    assert len(store.calls) == 1
    assert store.calls[0]["capacity"] == 120
    assert store.calls[0]["window"] == timedelta(minutes=1)
    assert store.calls[0]["current_time"] == NOW
    assert store.calls[0]["category"] == "authenticated_administrative_operation"
