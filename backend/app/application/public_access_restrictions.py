"""Coordination of independent public appointment access restrictions."""

from __future__ import annotations

from datetime import datetime

from backend.app.application.clock import Clock
from backend.app.application.public_credential_failures import (
    PublicCredentialFailureStore,
    RecordPublicCredentialFailure,
)
from backend.app.application.public_request_limit import (
    PUBLIC_APPOINTMENT_EVENT_CATEGORY,
    PUBLIC_APPOINTMENT_REQUEST_LIMIT,
    PUBLIC_APPOINTMENT_REQUEST_WINDOW,
    PUBLIC_READ_ACCEPTED_RESULT,
    PublicRequestRateLimitError,
    PublicRequestWindowStore,
)
from backend.app.domain.time import normalize_instant


PUBLIC_CREDENTIAL_OPERATION_CATEGORIES = frozenset(
    {
        "appointment_lookup",
        "appointment_modification",
        "appointment_cancellation",
    }
)


class CombinePublicAppointmentRestrictions:
    """Apply the later expiry when volume and credential restrictions overlap."""

    def __init__(
        self,
        *,
        request_store: PublicRequestWindowStore,
        credential_store: PublicCredentialFailureStore,
        clock: Clock,
        subject_fingerprint: bytes,
    ) -> None:
        if not isinstance(subject_fingerprint, bytes) or not subject_fingerprint:
            raise ValueError("public request subject fingerprint is invalid.")
        self._request_store = request_store
        self._credential_store = credential_store
        self._clock = clock
        self._subject_fingerprint = subject_fingerprint

    def ensure_allowed(self, category: str) -> None:
        """Deny until the later active restriction expires, without extending either."""

        if category not in PUBLIC_CREDENTIAL_OPERATION_CATEGORIES:
            raise ValueError("public credential operation category is invalid.")

        current_time = normalize_instant(self._clock.now())
        general_expiry = self._request_store.find_active_denial_expiry(
            subject_fingerprint=self._subject_fingerprint,
            category=PUBLIC_APPOINTMENT_EVENT_CATEGORY,
            result=PUBLIC_READ_ACCEPTED_RESULT,
            current_time=current_time,
            limit=PUBLIC_APPOINTMENT_REQUEST_LIMIT,
        )
        credential_expiry = self._credential_store.find_active_block_expiry(
            subject_fingerprint=self._subject_fingerprint,
            current_time=current_time,
        )
        active_expiries = tuple(
            expiry
            for expiry in (general_expiry, credential_expiry)
            if expiry is not None
        )
        if active_expiries:
            raise PublicRequestRateLimitError(
                "Public appointment access is temporarily restricted.",
                denied_until=max(active_expiries),
            )

        accepted = self._request_store.try_record_request(
            subject_fingerprint=self._subject_fingerprint,
            category=PUBLIC_APPOINTMENT_EVENT_CATEGORY,
            result=PUBLIC_READ_ACCEPTED_RESULT,
            current_time=current_time,
            expires_at=current_time + PUBLIC_APPOINTMENT_REQUEST_WINDOW,
            limit=PUBLIC_APPOINTMENT_REQUEST_LIMIT,
        )
        if accepted:
            return

        denial_expiry = self._request_store.find_active_denial_expiry(
            subject_fingerprint=self._subject_fingerprint,
            category=PUBLIC_APPOINTMENT_EVENT_CATEGORY,
            result=PUBLIC_READ_ACCEPTED_RESULT,
            current_time=current_time,
            limit=PUBLIC_APPOINTMENT_REQUEST_LIMIT,
        )
        raise PublicRequestRateLimitError(
            "Public appointment request limit exceeded.",
            denied_until=denial_expiry,
        )


class ProtectPublicAppointmentLookup:
    """Coordinate the approved public lookup restriction and failure accounting."""

    def __init__(
        self,
        *,
        restrictions: CombinePublicAppointmentRestrictions,
        failure_recorder: RecordPublicCredentialFailure,
        subject_fingerprint: bytes,
        operation_category: str = "appointment_lookup",
    ) -> None:
        if not isinstance(subject_fingerprint, bytes) or not subject_fingerprint:
            raise ValueError("public request subject fingerprint is invalid.")
        self._restrictions = restrictions
        self._failure_recorder = failure_recorder
        self._subject_fingerprint = subject_fingerprint
        self._operation_category = operation_category

    def ensure_allowed(self) -> None:
        """Apply volume and active-credential restrictions before the lookup."""

        self._restrictions.ensure_allowed(self._operation_category)

    def record_invalid_credential(self) -> None:
        """Record a rejected public code without retaining its plaintext value."""

        self._failure_recorder.record_failure(
            subject_fingerprint=self._subject_fingerprint
        )

    def record_valid_credential(self) -> None:
        """Preserve existing failures after a valid public lookup."""

        self._failure_recorder.record_success(
            subject_fingerprint=self._subject_fingerprint
        )
