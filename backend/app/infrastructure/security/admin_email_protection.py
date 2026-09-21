"""Purpose-separated protection for administrative email claims."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.application.entropy import SecretGenerator
from backend.app.domain.authentication.admin_email_claim import (
    normalize_administrative_email_address,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


ADMIN_EMAIL_AAD = b"beautyhub/admin-email/v1"
AES_GCM_NONCE_BYTES = 12


class AdministrativeEmailProtectionError(ValueError):
    """Raised when protected administrative email data is invalid."""


@dataclass(frozen=True)
class ProtectedAdministrativeEmail:
    """The encrypted and non-reversible forms stored for one email claim."""

    lookup_digest: bytes
    email_ciphertext: bytes
    key_version: str


class AdministrativeEmailProtector:
    """Encrypt email for delivery and derive a separate exact-match digest."""

    def __init__(
        self,
        *,
        key_ring: CryptographyKeyRing,
        secret_generator: SecretGenerator,
    ) -> None:
        self._encryption_key = key_ring.derive("admin-email-encryption")
        self._lookup_key = key_ring.derive("admin-email-lookup")
        self._key_version = key_ring.key_version
        self._secret_generator = secret_generator

    def protect(self, value: str) -> ProtectedAdministrativeEmail:
        """Normalize, encrypt and fingerprint one administrative email address."""

        normalized = normalize_administrative_email_address(value)
        encoded_value = normalized.encode("ascii")
        nonce = self._secret_generator.token_bytes(AES_GCM_NONCE_BYTES)
        if not isinstance(nonce, bytes) or len(nonce) != AES_GCM_NONCE_BYTES:
            raise AdministrativeEmailProtectionError(
                "administrative email encryption nonce is invalid."
            )
        ciphertext = AESGCM(self._encryption_key).encrypt(
            nonce,
            encoded_value,
            ADMIN_EMAIL_AAD,
        )
        return ProtectedAdministrativeEmail(
            lookup_digest=self.lookup_digest(value),
            email_ciphertext=nonce + ciphertext,
            key_version=self._key_version,
        )

    def lookup_digest(self, value: str) -> bytes:
        """Derive the canonical lookup digest without creating ciphertext."""

        normalized = normalize_administrative_email_address(value)
        return hmac.new(
            self._lookup_key,
            normalized.encode("ascii"),
            hashlib.sha256,
        ).digest()

    def decrypt(self, *, email_ciphertext: bytes, key_version: str) -> str:
        """Recover one email only when the configured key version authenticates it."""

        if key_version != self._key_version:
            raise AdministrativeEmailProtectionError(
                "administrative email ciphertext is invalid."
            )
        if (
            not isinstance(email_ciphertext, bytes)
            or len(email_ciphertext) <= AES_GCM_NONCE_BYTES
        ):
            raise AdministrativeEmailProtectionError(
                "administrative email ciphertext is invalid."
            )
        try:
            plaintext = AESGCM(self._encryption_key).decrypt(
                email_ciphertext[:AES_GCM_NONCE_BYTES],
                email_ciphertext[AES_GCM_NONCE_BYTES:],
                ADMIN_EMAIL_AAD,
            )
            return plaintext.decode("ascii")
        except (InvalidTag, UnicodeDecodeError, ValueError) as error:
            raise AdministrativeEmailProtectionError(
                "administrative email ciphertext is invalid."
            ) from error
