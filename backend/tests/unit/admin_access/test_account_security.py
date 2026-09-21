"""T014 unit evidence for administrative account-security timing rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.domain.authentication.account_security import (
    ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW,
    AdministrativeAccountSecurityInvariantError,
    AdministrativeCredentialFailureResult,
    is_administrative_account_locked,
)


NOW = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)


def test_t014_keeps_an_account_locked_until_the_exact_expiry() -> None:
    lock_until = NOW + ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW

    assert is_administrative_account_locked(
        lock_until=lock_until,
        now=lock_until - timedelta(microseconds=1),
    )
    assert not is_administrative_account_locked(lock_until=lock_until, now=lock_until)


def test_t014_rejects_a_blocked_result_without_an_expiry() -> None:
    with pytest.raises(AdministrativeAccountSecurityInvariantError):
        AdministrativeCredentialFailureResult(
            failure_count=5,
            lock_until=None,
            blocked=True,
        )
