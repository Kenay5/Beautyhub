"""Sanitized technical logging for security-sensitive BeautyHub flows."""

from __future__ import annotations

import logging


_ALLOWED_EVENTS = frozenset(
    {
        "credential_rejected",
        "security_delivery_failed",
        "security_link_delivery_failed",
        "unexpected_http_error",
    }
)
_ALLOWED_OUTCOMES = frozenset({"accepted", "failed", "rejected"})


def log_security_event(*, event: str, outcome: str) -> None:
    """Record a controlled technical event without accepting sensitive context."""

    if event not in _ALLOWED_EVENTS:
        raise ValueError("security log event is invalid.")
    if outcome not in _ALLOWED_OUTCOMES:
        raise ValueError("security log outcome is invalid.")

    logging.getLogger("beautyhub.security").info(
        "event=%s outcome=%s",
        event,
        outcome,
    )
