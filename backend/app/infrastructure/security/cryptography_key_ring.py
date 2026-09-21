"""External versioned root-key derivation for BeautyHub security adapters."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.app.infrastructure.settings import CryptographyKeyConfiguration


DERIVED_KEY_BYTES = 32
KEY_DERIVATION_PREFIX = b"beautyhub/cryptography/"
KEY_DERIVATION_SUFFIX = b"/v1"
SUPPORTED_KEY_PURPOSES = frozenset(
    {
        "admin-email-encryption",
        "admin-email-lookup",
        "security-delivery-idempotency",
        "admin-session-csrf-lookup",
        "admin-session-lookup",
        "private-code-encryption",
        "private-code-lookup",
        "rate-limit-ip-lookup",
        "recovery-code-lookup",
        "security-link-lookup",
        "totp-encryption",
    }
)


class CryptographyKeyConfigurationError(ValueError):
    """Raised when a configured root key cannot safely derive a subkey."""


class CryptographyKeyRing:
    """Derive purpose-separated keys without exposing the external root key."""

    def __init__(self, configuration: CryptographyKeyConfiguration) -> None:
        try:
            encoded_key = configuration.root_key.reveal().encode("ascii")
            root_key = base64.b64decode(
                encoded_key + b"=" * (-len(encoded_key) % 4),
                altchars=b"-_",
                validate=True,
            )
        except (UnicodeEncodeError, ValueError) as error:
            raise CryptographyKeyConfigurationError(
                "cryptography root key is invalid."
            ) from error

        if len(root_key) != DERIVED_KEY_BYTES:
            raise CryptographyKeyConfigurationError("cryptography root key is invalid.")

        self._root_key = root_key
        self.key_version = configuration.key_version

    def derive(self, purpose: str) -> bytes:
        """Return a stable 256-bit key for one approved, separated purpose."""

        if purpose not in SUPPORTED_KEY_PURPOSES:
            raise CryptographyKeyConfigurationError("cryptography key purpose is invalid.")

        info = (
            KEY_DERIVATION_PREFIX
            + self.key_version.encode("ascii")
            + b"/"
            + purpose.encode("ascii")
            + KEY_DERIVATION_SUFFIX
        )
        return HKDF(
            algorithm=hashes.SHA256(),
            length=DERIVED_KEY_BYTES,
            salt=None,
            info=info,
        ).derive(self._root_key)
