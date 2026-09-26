"""T052 unit evidence for security-change invalidation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.admin_access.security_change_invalidation import (
    InvalidateAfterSecurityChange,
)
from backend.app.application.clock import FixedClock


NOW_WITH_OFFSET = datetime(
    2032, 5, 6, 7, tzinfo=timezone(timedelta(hours=-5))
)


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[int, datetime]] = []

    def invalidate_after_security_change(
        self, *, account_id: int, current_time: datetime
    ) -> None:
        self.calls.append((account_id, current_time))


def test_t052_uses_one_normalized_instant_for_the_complete_invalidation() -> None:
    store = RecordingStore()

    InvalidateAfterSecurityChange(
        store=store,
        clock=FixedClock(NOW_WITH_OFFSET),
    ).execute(account_id=7)

    assert store.calls == [(7, datetime(2032, 5, 6, 12, tzinfo=timezone.utc))]


@pytest.mark.parametrize("account_id", [0, -1, True, "7"])
def test_t052_rejects_invalid_account_identifiers_without_mutation(account_id) -> None:
    store = RecordingStore()

    with pytest.raises(ValueError, match="administrative account identifier is invalid"):
        InvalidateAfterSecurityChange(
            store=store,
            clock=FixedClock(NOW_WITH_OFFSET),
        ).execute(account_id=account_id)

    assert store.calls == []
