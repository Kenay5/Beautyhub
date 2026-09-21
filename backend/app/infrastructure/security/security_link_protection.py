"""HMAC lookup protection for opaque administrative link tokens."""

from __future__ import annotations

import hashlib
import hmac

from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


SECURITY_LINK_TOKEN_BYTES = 32


class SecurityLinkProtectionError(ValueError):
    """Raised when a security-link token cannot be protected safely."""


class SecurityLinkProtector:
    """Store only a purpose-separated HMAC digest of a link token."""

    def __init__(self, *, key_ring: CryptographyKeyRing) -> None:
        self._lookup_key = key_ring.derive("security-link-lookup")
        self.key_version = key_ring.key_version

    def digest(self, token: bytes) -> bytes:
        """Return an exact-match digest for one 256-bit opaque token."""

        if not isinstance(token, bytes) or len(token) != SECURITY_LINK_TOKEN_BYTES:
            raise SecurityLinkProtectionError("security link token is invalid.")
        return hmac.new(self._lookup_key, token, hashlib.sha256).digest()
