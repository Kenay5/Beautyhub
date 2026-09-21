"""Purpose-separated HMAC protection for opaque session and CSRF values."""

from __future__ import annotations

import hashlib
import hmac

from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


ADMIN_SESSION_TOKEN_BYTES = 32
ADMIN_CSRF_TOKEN_BYTES = 32


class AdminSessionProtectionError(ValueError):
    """Raised when an opaque administrative session value is invalid."""


class AdminSessionProtector:
    """Create lookup digests without storing session or CSRF values in plaintext."""

    def __init__(self, *, key_ring: CryptographyKeyRing) -> None:
        self._session_lookup_key = key_ring.derive("admin-session-lookup")
        self._csrf_lookup_key = key_ring.derive("admin-session-csrf-lookup")
        self.key_version = key_ring.key_version

    def digest_session_token(self, token: bytes) -> bytes:
        """Return a digest for the approved 256-bit opaque session token."""

        self._validate_token(token, expected_size=ADMIN_SESSION_TOKEN_BYTES)
        return hmac.new(self._session_lookup_key, token, hashlib.sha256).digest()

    def digest_csrf_token(self, token: bytes) -> bytes:
        """Return a separate digest for the approved 256-bit CSRF token."""

        self._validate_token(token, expected_size=ADMIN_CSRF_TOKEN_BYTES)
        return hmac.new(self._csrf_lookup_key, token, hashlib.sha256).digest()

    @staticmethod
    def _validate_token(token: bytes, *, expected_size: int) -> None:
        if not isinstance(token, bytes) or len(token) != expected_size:
            raise AdminSessionProtectionError(
                "administrative session token is invalid."
            )
