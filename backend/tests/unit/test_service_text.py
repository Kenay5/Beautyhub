"""Unit tests for service name and description validation."""

import pytest

from backend.app.domain.service_text import (
    ServiceNameUniquenessError,
    ServiceTextValidationError,
    canonicalize_service_name,
    ensure_service_name_is_unique,
    validate_service_text,
)


def test_service_text_trims_outer_whitespace_and_preserves_visible_unicode() -> None:
    name, description = validate_service_text(
        "  Uñas ñ ✨ #1  ",
        "  Esmalte, diseño y brillo.  ",
    )

    assert name == "Uñas ñ ✨ #1"
    assert description == "Esmalte, diseño y brillo."


def test_service_text_keeps_an_optional_description_absent() -> None:
    name, description = validate_service_text("Manicure", None)

    assert name == "Manicure"
    assert description is None


@pytest.mark.parametrize(
    ("name", "description"),
    [
        ("Name\x00", None),
        ("Name", "Description\nwith a control"),
        ("Name\u200b", None),
    ],
)
def test_service_text_rejects_control_and_format_characters(
    name: str, description: str | None
) -> None:
    with pytest.raises(ServiceTextValidationError, match="control characters"):
        validate_service_text(name, description)


@pytest.mark.parametrize("name", ["", "   "])
def test_service_text_rejects_an_empty_name_after_trimming(name: str) -> None:
    with pytest.raises(ServiceTextValidationError, match="must not be empty"):
        validate_service_text(name, None)


@pytest.mark.parametrize("name", ["A", "A" * 100])
def test_service_text_accepts_name_length_boundaries(name: str) -> None:
    assert validate_service_text(name, None)[0] == name


def test_service_text_rejects_a_name_longer_than_100_characters() -> None:
    with pytest.raises(ServiceTextValidationError, match="must not exceed 100"):
        validate_service_text("A" * 101, None)


def test_service_text_accepts_a_250_character_description() -> None:
    description = "D" * 250

    assert validate_service_text("Manicure", description)[1] == description


def test_service_text_rejects_a_description_longer_than_250_characters() -> None:
    with pytest.raises(ServiceTextValidationError, match="must not exceed 250"):
        validate_service_text("Manicure", "D" * 251)


def test_service_name_canonicalization_ignores_outer_spaces_and_case() -> None:
    assert canonicalize_service_name("  MANICURE  ") == "manicure"


def test_service_name_uniqueness_rejects_a_canonical_duplicate() -> None:
    with pytest.raises(ServiceNameUniquenessError, match="must be unique"):
        ensure_service_name_is_unique("  MANICURE  ", ["Manicure"])


def test_service_name_uniqueness_accepts_a_distinct_name() -> None:
    assert ensure_service_name_is_unique("Pedicure", ["Manicure"]) == "Pedicure"
