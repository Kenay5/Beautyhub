"""Opaque account subjects for authenticated administrative rate limits."""

from __future__ import annotations

import hashlib
import hmac

from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


class AdministrativeRateLimitSubjectProtectionError(ValueError):
    """Raised when an authenticated account identifier cannot be protected."""


class AdministrativeRateLimitSubjectProtector:
    """Fingerprint account identifiers without persisting the identifier itself."""

    def __init__(self, *, key_ring: CryptographyKeyRing) -> None:
        self._fingerprint_key = key_ring.derive("rate-limit-account-lookup")
        self.key_version = key_ring.key_version

    def fingerprint_account(self, account_id: int) -> bytes:
        """Return a stable keyed fingerprint for one positive PostgreSQL account id."""

        if (
            isinstance(account_id, bool)
            or not isinstance(account_id, int)
            or not 1 <= account_id <= (2**63 - 1)
        ):
            raise AdministrativeRateLimitSubjectProtectionError(
                "administrative rate-limit account is invalid."
            )
        message = b"admin-account:" + account_id.to_bytes(8, "big", signed=False)
        return hmac.new(self._fingerprint_key, message, hashlib.sha256).digest()
