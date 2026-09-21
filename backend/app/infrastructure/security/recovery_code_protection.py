"""HMAC lookup protection for administrative recovery codes."""

from __future__ import annotations

import hashlib
import hmac

from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


class RecoveryCodeProtectionError(ValueError):
    """Raised when a recovery code cannot be protected safely."""


class RecoveryCodeProtector:
    """Store only an irreversible, purpose-separated code digest."""

    def __init__(self, *, key_ring: CryptographyKeyRing) -> None:
        self._lookup_key = key_ring.derive("recovery-code-lookup")
        self.key_version = key_ring.key_version

    def digest(self, code: str) -> bytes:
        """Return an HMAC digest without retaining or returning the code itself."""

        if not isinstance(code, str) or not code:
            raise RecoveryCodeProtectionError("recovery code is invalid.")
        try:
            encoded_code = code.encode("ascii")
        except UnicodeEncodeError as error:
            raise RecoveryCodeProtectionError("recovery code is invalid.") from error
        return hmac.new(self._lookup_key, encoded_code, hashlib.sha256).digest()
