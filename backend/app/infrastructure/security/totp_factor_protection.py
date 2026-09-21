"""Authenticated encryption for confirmed administrative TOTP secrets."""

from __future__ import annotations

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.application.entropy import SecretGenerator
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import (
    AES_GCM_NONCE_BYTES,
)


TOTP_FACTOR_AAD_PREFIX = b"beautyhub/totp-factor/v1/"


class TotpFactorProtectionError(ValueError):
    """Raised when a confirmed TOTP secret cannot be protected safely."""


class TotpFactorProtector:
    """Encrypt a factor only for the account to which it belongs."""

    def __init__(
        self,
        *,
        key_ring: CryptographyKeyRing,
        secret_generator: SecretGenerator,
    ) -> None:
        self._encryption_key = key_ring.derive("totp-encryption")
        self.key_version = key_ring.key_version
        self._secret_generator = secret_generator

    def encrypt(self, *, account_id: int, secret: bytes) -> bytes:
        """Return authenticated ciphertext with account-bound associated data."""

        if not isinstance(secret, bytes) or not secret:
            raise TotpFactorProtectionError("TOTP factor secret is invalid.")
        nonce = self._secret_generator.token_bytes(AES_GCM_NONCE_BYTES)
        if not isinstance(nonce, bytes) or len(nonce) != AES_GCM_NONCE_BYTES:
            raise TotpFactorProtectionError("TOTP factor nonce is invalid.")
        return nonce + AESGCM(self._encryption_key).encrypt(
            nonce, secret, self._associated_data(account_id)
        )

    def decrypt(self, *, account_id: int, ciphertext: bytes) -> bytes:
        """Recover a secret only for its original account and valid ciphertext."""

        if not isinstance(ciphertext, bytes) or len(ciphertext) <= AES_GCM_NONCE_BYTES:
            raise TotpFactorProtectionError("TOTP factor ciphertext is invalid.")
        try:
            return AESGCM(self._encryption_key).decrypt(
                ciphertext[:AES_GCM_NONCE_BYTES],
                ciphertext[AES_GCM_NONCE_BYTES:],
                self._associated_data(account_id),
            )
        except (InvalidTag, ValueError) as error:
            raise TotpFactorProtectionError(
                "TOTP factor ciphertext is invalid."
            ) from error

    def _associated_data(self, account_id: int) -> bytes:
        if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
            raise TotpFactorProtectionError("TOTP factor account is invalid.")
        return (
            TOTP_FACTOR_AAD_PREFIX
            + self.key_version.encode("ascii")
            + b"/"
            + str(account_id).encode("ascii")
        )
