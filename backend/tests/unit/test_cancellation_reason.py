"""Focused coverage for RF-07-CA-05 cancellation reason validation."""

import pytest

from backend.app.domain.cancellation_reason import (
    CancellationReasonValidationError,
    normalize_cancellation_reason,
)


def test_cancellation_reason_trims_outer_spaces_and_preserves_visible_unicode() -> None:
    assert normalize_cancellation_reason("  Llegó un imprevisto ✨  ") == "Llegó un imprevisto ✨"


@pytest.mark.parametrize("value", [None, "", "   ", "\u00a0\u00a0"])
def test_cancellation_reason_treats_absent_or_empty_text_as_no_reason(value: str | None) -> None:
    assert normalize_cancellation_reason(value) is None


@pytest.mark.parametrize("value", ["Motivo\x00", "Motivo\n", "Motivo\u200b"])
def test_cancellation_reason_rejects_control_or_format_characters(value: str) -> None:
    with pytest.raises(CancellationReasonValidationError, match="control characters"):
        normalize_cancellation_reason(value)


def test_cancellation_reason_accepts_exactly_250_visible_unicode_characters() -> None:
    reason = "ñ" * 250

    assert normalize_cancellation_reason(reason) == reason


def test_cancellation_reason_rejects_more_than_250_visible_unicode_characters() -> None:
    with pytest.raises(CancellationReasonValidationError, match="must not exceed 250"):
        normalize_cancellation_reason("✨" * 251)


@pytest.mark.parametrize("value", [0, object()])
def test_cancellation_reason_rejects_non_text_values(value: object) -> None:
    with pytest.raises(CancellationReasonValidationError, match="must be a string"):
        normalize_cancellation_reason(value)  # type: ignore[arg-type]
