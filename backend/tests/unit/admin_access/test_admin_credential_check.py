"""T046 unit evidence for the pre-verification administrative lock guard."""

from datetime import datetime, timezone

import pytest

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
)
from backend.app.application.clock import FixedClock


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)


class Store:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.calls = []

    def ensure_credential_check_allowed(self, *, account_id, current_time):
        self.calls.append((account_id, current_time))
        return self.allowed


def test_t046_delegates_the_controlled_time_to_the_pre_verification_guard() -> None:
    store = Store(allowed=False)

    allowed = EnsureAdministrativeCredentialCheck(
        store=store,
        clock=FixedClock(NOW),
    ).ensure_allowed(account_id=7)

    assert not allowed
    assert store.calls == [(7, NOW)]


@pytest.mark.parametrize("account_id", (0, -1, True, "7"))
def test_t046_rejects_invalid_account_identifiers_before_the_store(account_id) -> None:
    store = Store(allowed=True)
    guard = EnsureAdministrativeCredentialCheck(store=store, clock=FixedClock(NOW))

    with pytest.raises(ValueError):
        guard.ensure_allowed(account_id=account_id)

    assert store.calls == []
