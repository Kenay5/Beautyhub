"""Keyed, non-reversible fingerprints for public request IP subjects."""

from __future__ import annotations

import hashlib
import hmac
from ipaddress import ip_address

from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


class PublicRequestSubjectProtectionError(ValueError):
    """Raised when an IP subject cannot be protected safely."""


class PublicRequestSubjectProtector:
    """Produce an HMAC fingerprint without retaining the source IP."""

    def __init__(self, *, key_ring: CryptographyKeyRing) -> None:
        self._fingerprint_key = key_ring.derive("rate-limit-ip-lookup")
        self.key_version = key_ring.key_version

    def fingerprint_ip(self, value: str) -> bytes:
        """Normalize an IPv4/IPv6 address and return only its keyed digest."""

        try:
            address = ip_address(value)
        except ValueError as error:
            raise PublicRequestSubjectProtectionError(
                "public request client address is invalid."
            ) from error
        message = bytes((address.version,)) + address.packed
        return hmac.new(self._fingerprint_key, message, hashlib.sha256).digest()
