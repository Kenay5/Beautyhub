"""Approved mutable fields for a public appointment modification request."""

from __future__ import annotations

from collections.abc import Mapping


PUBLIC_APPOINTMENT_MODIFICATION_FIELDS = frozenset(
    {
        "scheduledStart",
        "branch",
        "serviceName",
    }
)


class PublicAppointmentModificationFieldError(ValueError):
    """Raised when a public request attempts to change an unapproved field."""


def require_only_public_appointment_modification_fields(
    changes: Mapping[str, object],
) -> None:
    """Reject public changes other than appointment start, branch, or service.

    ``scheduledStart`` carries the approved public date and time together as one
    explicit instant. Value validation and the actual schedule mutation remain
    deliberately deferred to T075.
    """

    unsupported_fields = set(changes) - PUBLIC_APPOINTMENT_MODIFICATION_FIELDS
    if unsupported_fields:
        raise PublicAppointmentModificationFieldError(
            "public appointment modification contains an unapproved field."
        )
