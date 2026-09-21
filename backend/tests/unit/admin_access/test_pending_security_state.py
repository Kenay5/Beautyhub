"""T029 unit evidence for coherent pending-state cleanup."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.application.admin_access.pending_security_state import (
    DiscardPendingSecurityState,
)
from backend.app.application.clock import FixedClock


NOW = datetime(2032, 5, 6, 12, tzinfo=timezone.utc)


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None, datetime]] = []

    def discard_for_expired_link(self, *, account_id, purpose, current_time) -> None:
        self.calls.append(("expired", account_id, purpose, current_time))

    def discard_abandoned_setup(self, *, account_id, flow, current_time) -> None:
        self.calls.append(("abandoned", account_id, flow, current_time))

    def discard_for_replaced_link(self, *, account_id, purpose, current_time) -> None:
        self.calls.append(("replaced", account_id, purpose, current_time))

    def discard_after_completed_security_change(self, *, account_id, current_time) -> None:
        self.calls.append(("completed", account_id, None, current_time))


def test_t029_uses_the_controlled_clock_for_each_pending_cleanup_reason() -> None:
    store = RecordingStore()
    cleanup = DiscardPendingSecurityState(store=store, clock=FixedClock(NOW))

    cleanup.expired_link(account_id=7, purpose="initial_activation")
    cleanup.abandoned_setup(account_id=7, flow="owner_activation")
    cleanup.replaced_link(account_id=7, purpose="totp_replacement")
    cleanup.completed_security_change(account_id=7)

    assert store.calls == [
        ("expired", 7, "initial_activation", NOW),
        ("abandoned", 7, "owner_activation", NOW),
        ("replaced", 7, "totp_replacement", NOW),
        ("completed", 7, None, NOW),
    ]


@pytest.mark.parametrize("account_id", [0, -1, True, "7"])
def test_t029_rejects_invalid_account_identifiers_without_any_cleanup(account_id) -> None:
    store = RecordingStore()
    cleanup = DiscardPendingSecurityState(store=store, clock=FixedClock(NOW))

    with pytest.raises(ValueError, match="administrative account identifier is invalid"):
        cleanup.completed_security_change(account_id=account_id)

    assert store.calls == []
