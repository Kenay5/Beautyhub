"""Authenticated encryption for unconfirmed TOTP setup material."""

from __future__ import annotations

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.application.entropy import SecretGenerator
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


TOTP_SETUP_AAD_PREFIX = b"beautyhub/pending-totp/v1/"
AES_GCM_NONCE_BYTES = 12
_VALID_FLOWS = frozenset({"owner_activation", "staff_activation", "totp_replacement"})


class PendingTotpProtectionError(ValueError):
    """Raised when pending TOTP material cannot safely be protected."""


class PendingTotpProtector:
    """Encrypt unconfirmed TOTP material with the approved TOTP subkey."""

    def __init__(
        self,
        *,
        key_ring: CryptographyKeyRing,
        secret_generator: SecretGenerator,
    ) -> None:
        self._encryption_key = key_ring.derive("totp-encryption")
        self.key_version = key_ring.key_version
        self._secret_generator = secret_generator

    def encrypt(self, *, account_id: int, flow: str, secret: bytes) -> bytes:
        """Encrypt pending material bound to its account and setup flow."""

        if not isinstance(secret, bytes) or not secret:
            raise PendingTotpProtectionError("pending TOTP secret is invalid.")
        nonce = self._secret_generator.token_bytes(AES_GCM_NONCE_BYTES)
        if not isinstance(nonce, bytes) or len(nonce) != AES_GCM_NONCE_BYTES:
            raise PendingTotpProtectionError("pending TOTP nonce is invalid.")
        return nonce + AESGCM(self._encryption_key).encrypt(
            nonce, secret, self._associated_data(account_id=account_id, flow=flow)
        )

    def decrypt(self, *, account_id: int, flow: str, ciphertext: bytes) -> bytes:
        """Recover pending material only in its original setup context."""

        if not isinstance(ciphertext, bytes) or len(ciphertext) <= AES_GCM_NONCE_BYTES:
            raise PendingTotpProtectionError("pending TOTP ciphertext is invalid.")
        try:
            return AESGCM(self._encryption_key).decrypt(
                ciphertext[:AES_GCM_NONCE_BYTES],
                ciphertext[AES_GCM_NONCE_BYTES:],
                self._associated_data(account_id=account_id, flow=flow),
            )
        except (InvalidTag, ValueError) as error:
            raise PendingTotpProtectionError(
                "pending TOTP ciphertext is invalid."
            ) from error

    def _associated_data(self, *, account_id: int, flow: str) -> bytes:
        if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
            raise PendingTotpProtectionError("pending TOTP account is invalid.")
        if flow not in _VALID_FLOWS:
            raise PendingTotpProtectionError("pending TOTP flow is invalid.")
        return (
            TOTP_SETUP_AAD_PREFIX
            + self.key_version.encode("ascii")
            + b"/"
            + str(account_id).encode("ascii")
            + b"/"
            + flow.encode("ascii")
        )
