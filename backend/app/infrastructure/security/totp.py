"""RFC 6238 TOTP generation and verification for administrative factors."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Collection
from datetime import datetime, timezone
from typing import Final

import pyotp

from backend.app.application.entropy import SecretGenerator


TOTP_SECRET_BYTES: Final = 20
TOTP_DIGITS: Final = 6
TOTP_PERIOD_SECONDS: Final = 30
TOTP_ACCEPTED_PERIOD_OFFSETS: Final = (-1, 0, 1)
TOTP_DEFAULT_ALGORITHM: Final = "SHA1"
_TOTP_DIGESTS: Final = {
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
}


class TotpError(ValueError):
    """Raised when TOTP input cannot safely be generated or verified."""


class TotpAuthenticator:
    """Generate secrets and verify only the approved standard TOTP window."""

    def __init__(self, *, secret_generator: SecretGenerator) -> None:
        self._secret_generator = secret_generator

    def generate_secret(self) -> bytes:
        """Generate a 160-bit, unpadded Base32 secret for a compatible app."""

        entropy = self._secret_generator.token_bytes(TOTP_SECRET_BYTES)
        if not isinstance(entropy, bytes) or len(entropy) != TOTP_SECRET_BYTES:
            raise TotpError("TOTP secret entropy is invalid.")
        return base64.b32encode(entropy).rstrip(b"=")

    def provisioning_uri(
        self,
        *,
        secret: bytes,
        account_label: str,
        issuer: str,
    ) -> str:
        """Build a standard local provisioning URI without contacting a service."""

        secret_value = _validate_secret(secret)
        if not isinstance(account_label, str) or not account_label.strip():
            raise TotpError("TOTP account label is invalid.")
        if not isinstance(issuer, str) or not issuer.strip():
            raise TotpError("TOTP issuer is invalid.")
        return pyotp.TOTP(
            secret_value,
            digits=TOTP_DIGITS,
            interval=TOTP_PERIOD_SECONDS,
        ).provisioning_uri(
            name=account_label.strip(),
            issuer_name=issuer.strip(),
        )

    def verify(
        self,
        *,
        secret: bytes,
        code: str,
        now: datetime,
        used_period_counters: Collection[int] = (),
        algorithm: str = TOTP_DEFAULT_ALGORITHM,
    ) -> int | None:
        """Return an unused accepted period without consuming it.

        The caller must persist the returned counter in its successful transaction.
        This keeps rejected or incomplete operations from consuming a valid TOTP.
        """

        secret_value = _validate_secret(secret)
        if not _is_valid_code(code):
            return None
        current_counter = _period_counter(now)
        digest = _digest_for(algorithm)
        totp = pyotp.TOTP(
            secret_value,
            digits=TOTP_DIGITS,
            interval=TOTP_PERIOD_SECONDS,
            digest=digest,
        )

        for offset in TOTP_ACCEPTED_PERIOD_OFFSETS:
            period_counter = current_counter + offset
            if period_counter < 0 or period_counter in used_period_counters:
                continue
            if totp.verify(code, for_time=period_counter * TOTP_PERIOD_SECONDS):
                return period_counter
        return None


def _validate_secret(secret: bytes) -> str:
    if not isinstance(secret, bytes) or not secret:
        raise TotpError("TOTP secret is invalid.")
    try:
        secret_value = secret.decode("ascii")
        base64.b32decode(secret_value, casefold=False)
    except (UnicodeDecodeError, ValueError) as error:
        raise TotpError("TOTP secret is invalid.") from error
    return secret_value


def _is_valid_code(code: str) -> bool:
    return (
        isinstance(code, str)
        and len(code) == TOTP_DIGITS
        and code.isascii()
        and code.isdecimal()
    )


def _period_counter(now: datetime) -> int:
    if now.tzinfo is None or now.utcoffset() is None:
        raise TotpError("TOTP clock instant must be aware.")
    seconds_since_epoch = int(now.astimezone(timezone.utc).timestamp())
    if seconds_since_epoch < 0:
        raise TotpError("TOTP clock instant is invalid.")
    return seconds_since_epoch // TOTP_PERIOD_SECONDS


def _digest_for(algorithm: str):
    try:
        return _TOTP_DIGESTS[algorithm]
    except KeyError as error:
        raise TotpError("TOTP algorithm is invalid.") from error
