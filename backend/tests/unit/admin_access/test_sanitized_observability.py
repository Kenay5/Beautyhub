"""T006 unit evidence for controlled technical security logs."""

from __future__ import annotations

import logging

import pytest

from backend.app.infrastructure.security.sanitized_observability import (
    log_security_event,
)


def test_t006_logs_only_an_approved_event_and_outcome(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="beautyhub.security"):
        log_security_event(event="credential_rejected", outcome="rejected")

    assert caplog.messages == ["event=credential_rejected outcome=rejected"]


@pytest.mark.parametrize(
    ("event", "outcome"),
    (
        ("client@example.invalid", "rejected"),
        ("credential_rejected", "security-token-value"),
    ),
)
def test_t006_rejects_uncontrolled_log_values(event: str, outcome: str) -> None:
    with pytest.raises(ValueError):
        log_security_event(event=event, outcome=outcome)
