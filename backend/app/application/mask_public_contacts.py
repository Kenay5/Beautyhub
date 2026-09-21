"""Deterministic masking rules for contacts shown in public appointment views."""

from __future__ import annotations


class PublicContactMaskingError(ValueError):
    """Raised when a contact cannot be safely masked."""


def mask_public_phone(phone: str) -> str:
    """Hide the first six digits and retain only the final four digits."""

    if not isinstance(phone, str) or len(phone) != 10 or not phone.isascii() or not phone.isdigit():
        raise PublicContactMaskingError("phone cannot be masked safely.")
    return f"******{phone[-4:]}"


def mask_public_email(email: str) -> str:
    """Keep the first local/domain characters and the final domain extension."""

    if not isinstance(email, str) or email.count("@") != 1:
        raise PublicContactMaskingError("email cannot be masked safely.")
    local, domain = email.split("@", 1)
    if not local or "." not in domain:
        raise PublicContactMaskingError("email cannot be masked safely.")
    extension = domain.rsplit(".", 1)[1]
    if not extension:
        raise PublicContactMaskingError("email cannot be masked safely.")
    return f"{local[0]}***@{domain[0]}***.{extension}"
