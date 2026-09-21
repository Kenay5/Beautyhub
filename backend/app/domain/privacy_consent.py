"""Consent evidence required when a BeautyHub appointment is created."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


PUBLIC_APPOINTMENT_ORIGIN = "public"
ADMINISTRATIVE_APPOINTMENT_ORIGIN = "administrative"
APPROVED_APPOINTMENT_ORIGINS = (
    PUBLIC_APPOINTMENT_ORIGIN,
    ADMINISTRATIVE_APPOINTMENT_ORIGIN,
)


class PrivacyConsentValidationError(ValueError):
    """Raised when appointment consent evidence is incomplete or inconsistent."""


@dataclass(frozen=True)
class PrivacyConsentEvidence:
    """Immutable evidence retained with one appointment under RF-03-CA-13."""

    privacy_notice_version_id: int
    accepted_at: datetime
    origin: str
    contact_processing_authorized: bool
    adult_responsibility_declared: bool
    confirmed_by_account_id: int | None


def create_privacy_consent_evidence(
    *,
    privacy_notice_version_id: int,
    accepted_at: datetime,
    origin: str,
    contact_processing_authorized: bool,
    adult_responsibility_declared: bool,
    confirmed_by_account_id: int | None,
) -> PrivacyConsentEvidence:
    """Validate the consent evidence that must accompany a new appointment."""

    _validate_privacy_notice_version_id(privacy_notice_version_id)
    _validate_accepted_at(accepted_at)
    _validate_origin(origin)
    _require_authorization(
        contact_processing_authorized,
        "contact processing authorization is required.",
    )
    _require_authorization(
        adult_responsibility_declared,
        "adult responsibility declaration is required.",
    )
    _validate_responsible_account(origin, confirmed_by_account_id)

    return PrivacyConsentEvidence(
        privacy_notice_version_id=privacy_notice_version_id,
        accepted_at=accepted_at,
        origin=origin,
        contact_processing_authorized=contact_processing_authorized,
        adult_responsibility_declared=adult_responsibility_declared,
        confirmed_by_account_id=confirmed_by_account_id,
    )


def _validate_privacy_notice_version_id(privacy_notice_version_id: int) -> None:
    if (
        isinstance(privacy_notice_version_id, bool)
        or not isinstance(privacy_notice_version_id, int)
        or privacy_notice_version_id <= 0
    ):
        raise PrivacyConsentValidationError(
            "privacy notice version identifier must be a positive integer."
        )


def _validate_accepted_at(accepted_at: datetime) -> None:
    if not isinstance(accepted_at, datetime):
        raise PrivacyConsentValidationError("consent acceptance time must be a datetime.")
    if accepted_at.tzinfo is None or accepted_at.utcoffset() is None:
        raise PrivacyConsentValidationError(
            "consent acceptance time must include a timezone."
        )


def _validate_origin(origin: str) -> None:
    if origin not in APPROVED_APPOINTMENT_ORIGINS:
        raise PrivacyConsentValidationError("appointment origin is not approved.")


def _require_authorization(value: bool, message: str) -> None:
    if value is not True:
        raise PrivacyConsentValidationError(message)


def _validate_responsible_account(
    origin: str,
    confirmed_by_account_id: int | None,
) -> None:
    if origin == PUBLIC_APPOINTMENT_ORIGIN:
        if confirmed_by_account_id is not None:
            raise PrivacyConsentValidationError(
                "public appointments cannot have a responsible account."
            )
        return

    if (
        isinstance(confirmed_by_account_id, bool)
        or not isinstance(confirmed_by_account_id, int)
        or confirmed_by_account_id <= 0
    ):
        raise PrivacyConsentValidationError(
            "administrative appointments require a responsible account."
        )
