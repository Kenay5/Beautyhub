"""HTTP-safe transport helpers for opaque administrative security-link tokens."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from backend.app.infrastructure.security.security_link_protection import (
    SECURITY_LINK_TOKEN_BYTES,
)


SECURITY_LINK_TOKEN_ENCODED_LENGTH = 43
_SECURITY_LINK_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def encode_security_link_token(token: bytes) -> str:
    """Encode one 256-bit token without padding for URL fragments and JSON bodies."""

    if not isinstance(token, bytes) or len(token) != SECURITY_LINK_TOKEN_BYTES:
        raise ValueError("security link token is invalid.")
    return base64.urlsafe_b64encode(token).rstrip(b"=").decode("ascii")


def decode_security_link_token(value: str) -> bytes:
    """Decode only the canonical unpadded representation of one 256-bit token."""

    if not isinstance(value, str) or _SECURITY_LINK_TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError("security link token is invalid.")
    try:
        token = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("security link token is invalid.") from error
    if len(token) != SECURITY_LINK_TOKEN_BYTES or encode_security_link_token(token) != value:
        raise ValueError("security link token is invalid.")
    return token


def security_link_fragment(token: bytes) -> str:
    """Build the fragment-only token carrier used by same-origin security links."""

    return f"#token={encode_security_link_token(token)}"


class SecurityLinkTokenBody(BaseModel):
    """Reusable body contract for public security-link operations."""

    token: Annotated[
        str,
        Field(
            min_length=SECURITY_LINK_TOKEN_ENCODED_LENGTH,
            max_length=SECURITY_LINK_TOKEN_ENCODED_LENGTH,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ]

    @field_validator("token")
    @classmethod
    def require_canonical_token(cls, value: str) -> str:
        decode_security_link_token(value)
        return value

    def decoded_token(self) -> bytes:
        """Return the validated token for application-layer inspection or consumption."""

        return decode_security_link_token(self.token)
