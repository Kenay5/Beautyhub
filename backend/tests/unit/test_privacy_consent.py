"""Unit tests for the appointment consent evidence required by T045."""

from datetime import datetime, timezone

import pytest

from backend.app.domain.privacy_consent import (
    ADMINISTRATIVE_APPOINTMENT_ORIGIN,
    PUBLIC_APPOINTMENT_ORIGIN,
    PrivacyConsentEvidence,
    PrivacyConsentValidationError,
    create_privacy_consent_evidence,
)


def valid_consent_values(**overrides: object) -> dict[str, object]:
    return {
        "privacy_notice_version_id": 7,
        "accepted_at": datetime(2030, 6, 1, 12, tzinfo=timezone.utc),
        "origin": PUBLIC_APPOINTMENT_ORIGIN,
        "contact_processing_authorized": True,
        "adult_responsibility_declared": True,
        "confirmed_by_account_id": None,
        **overrides,
    }


def create_valid_consent(**overrides: object) -> PrivacyConsentEvidence:
    return create_privacy_consent_evidence(**valid_consent_values(**overrides))  # type: ignore[arg-type]


def test_public_consent_evidence_preserves_all_required_values() -> None:
    accepted_at = datetime(2030, 6, 1, 12, tzinfo=timezone.utc)

    evidence = create_valid_consent(accepted_at=accepted_at)

    assert evidence == PrivacyConsentEvidence(
        privacy_notice_version_id=7,
        accepted_at=accepted_at,
        origin=PUBLIC_APPOINTMENT_ORIGIN,
        contact_processing_authorized=True,
        adult_responsibility_declared=True,
        confirmed_by_account_id=None,
    )


def test_administrative_consent_evidence_preserves_responsible_account() -> None:
    evidence = create_valid_consent(
        origin=ADMINISTRATIVE_APPOINTMENT_ORIGIN,
        confirmed_by_account_id=23,
    )

    assert evidence.origin == ADMINISTRATIVE_APPOINTMENT_ORIGIN
    assert evidence.confirmed_by_account_id == 23


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contact_processing_authorized", False),
        ("contact_processing_authorized", "true"),
        ("adult_responsibility_declared", False),
        ("adult_responsibility_declared", 1),
    ],
)
def test_consent_rejects_missing_required_authorizations(
    field: str,
    value: object,
) -> None:
    with pytest.raises(PrivacyConsentValidationError):
        create_valid_consent(**{field: value})


@pytest.mark.parametrize(
    "privacy_notice_version_id",
    [0, -1, True, "7"],
)
def test_consent_requires_a_persistable_notice_version(
    privacy_notice_version_id: object,
) -> None:
    with pytest.raises(PrivacyConsentValidationError):
        create_valid_consent(privacy_notice_version_id=privacy_notice_version_id)


def test_consent_requires_a_timezone_aware_acceptance_instant() -> None:
    with pytest.raises(PrivacyConsentValidationError):
        create_valid_consent(accepted_at=datetime(2030, 6, 1, 12))


@pytest.mark.parametrize("origin", ["", "staff", "PUBLIC", None])
def test_consent_rejects_unapproved_origins(origin: object) -> None:
    with pytest.raises(PrivacyConsentValidationError):
        create_valid_consent(origin=origin)


def test_public_consent_rejects_a_responsible_account() -> None:
    with pytest.raises(PrivacyConsentValidationError):
        create_valid_consent(confirmed_by_account_id=23)


@pytest.mark.parametrize("confirmed_by_account_id", [None, 0, -1, True, "23"])
def test_administrative_consent_requires_a_responsible_account(
    confirmed_by_account_id: object,
) -> None:
    with pytest.raises(PrivacyConsentValidationError):
        create_valid_consent(
            origin=ADMINISTRATIVE_APPOINTMENT_ORIGIN,
            confirmed_by_account_id=confirmed_by_account_id,
        )
