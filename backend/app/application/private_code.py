"""Opaque private-code generation for BeautyHub appointments."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass, field

from backend.app.application.entropy import SecretGenerator


PRIVATE_CODE_ENTROPY_BYTES = 16


class PrivateCodeGenerationError(ValueError):
    """Raised when a secret generator cannot provide the required entropy."""


@dataclass(frozen=True)
class PrivateCode:
    """A private appointment code that must not be rendered by diagnostic output."""

    value: str = field(repr=False)
    entropy_bytes: int = PRIVATE_CODE_ENTROPY_BYTES


def generate_private_code(secret_generator: SecretGenerator) -> PrivateCode:
    """Generate an opaque code with the approved minimum of 128 random bits."""

    token = secret_generator.token_bytes(PRIVATE_CODE_ENTROPY_BYTES)
    if not isinstance(token, bytes) or len(token) != PRIVATE_CODE_ENTROPY_BYTES:
        raise PrivateCodeGenerationError(
            "private code generator did not return the required entropy."
        )

    return PrivateCode(
        value=urlsafe_b64encode(token).decode("ascii").rstrip("="),
    )
