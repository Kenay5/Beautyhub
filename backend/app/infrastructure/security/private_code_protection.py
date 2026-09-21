"""AES-GCM encryption and HMAC lookup protection for private appointment codes."""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.app.application.entropy import SecretGenerator
from backend.app.application.private_code import PrivateCode
from backend.app.infrastructure.settings import SecretValue


MASTER_KEY_BYTES = 32
AES_GCM_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
HMAC_DIGEST_BYTES = 32
PRIVATE_CODE_AAD = b"beautyhub/private-code/v1"
PRIVATE_CODE_ENCRYPTION_INFO = b"beautyhub/private-code/encryption/v1"
PRIVATE_CODE_LOOKUP_INFO = b"beautyhub/private-code/lookup/v1"


class PrivateCodeProtectionError(ValueError):
    """Raised when private-code protection cannot safely complete."""


class PrivateCodeDecryptionError(ValueError):
    """Raised when an encrypted private code cannot be authenticated."""


class PrivateCodeProtector:
    """Protect private codes while keeping the configured root key external."""

    def __init__(
        self,
        *,
        master_key: SecretValue,
        secret_generator: SecretGenerator,
    ) -> None:
        root_key = _decode_master_key(master_key)
        self._encryption_key = _derive_subkey(root_key, PRIVATE_CODE_ENCRYPTION_INFO)
        self._lookup_key = _derive_subkey(root_key, PRIVATE_CODE_LOOKUP_INFO)
        self._secret_generator = secret_generator

    def digest(self, secret: str) -> bytes:
        """Return the HMAC-SHA-256 value used for exact private-code lookup."""

        encoded_secret = _encode_secret(secret)
        return hmac.new(self._lookup_key, encoded_secret, hashlib.sha256).digest()

    def encrypt(self, private_code: PrivateCode) -> bytes:
        """Encrypt one generated code with AES-256-GCM and a fresh nonce."""

        if not isinstance(private_code, PrivateCode):
            raise PrivateCodeProtectionError("private code must be generated first.")

        nonce = self._secret_generator.token_bytes(AES_GCM_NONCE_BYTES)
        if not isinstance(nonce, bytes) or len(nonce) != AES_GCM_NONCE_BYTES:
            raise PrivateCodeProtectionError(
                "private code encryption nonce has an invalid length."
            )

        ciphertext = AESGCM(self._encryption_key).encrypt(
            nonce,
            _encode_secret(private_code.value),
            PRIVATE_CODE_AAD,
        )
        return nonce + ciphertext

    def decrypt(self, ciphertext: bytes) -> PrivateCode:
        """Recover a private code only after authenticated AES-GCM decryption."""

        if not isinstance(ciphertext, bytes) or len(ciphertext) <= AES_GCM_NONCE_BYTES:
            raise PrivateCodeDecryptionError("private code ciphertext is invalid.")

        nonce = ciphertext[:AES_GCM_NONCE_BYTES]
        encrypted_value = ciphertext[AES_GCM_NONCE_BYTES:]
        try:
            decrypted_value = AESGCM(self._encryption_key).decrypt(
                nonce,
                encrypted_value,
                PRIVATE_CODE_AAD,
            )
            value = decrypted_value.decode("ascii")
        except (InvalidTag, UnicodeDecodeError, ValueError) as error:
            raise PrivateCodeDecryptionError("private code ciphertext is invalid.") from error

        return PrivateCode(value=value)


def _decode_master_key(master_key: SecretValue) -> bytes:
    try:
        encoded_key = master_key.reveal().encode("ascii")
        decoded_key = base64.b64decode(
            encoded_key + b"=" * (-len(encoded_key) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeEncodeError, ValueError) as error:
        raise PrivateCodeProtectionError("private code master key is invalid.") from error

    if len(decoded_key) != MASTER_KEY_BYTES:
        raise PrivateCodeProtectionError("private code master key is invalid.")
    return decoded_key


def _derive_subkey(root_key: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=AES_GCM_KEY_BYTES,
        salt=None,
        info=info,
    ).derive(root_key)


def _encode_secret(secret: str) -> bytes:
    if not isinstance(secret, str) or not secret:
        raise PrivateCodeProtectionError("secret is invalid.")
    try:
        return secret.encode("ascii")
    except UnicodeEncodeError as error:
        raise PrivateCodeProtectionError("secret is invalid.") from error
