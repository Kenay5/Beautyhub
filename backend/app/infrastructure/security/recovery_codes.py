"""Generation and non-consuming validation of administrative recovery codes."""

from __future__ import annotations

import hmac
from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from backend.app.application.entropy import SecretGenerator
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)


RECOVERY_CODE_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECOVERY_CODE_LENGTH: Final = 16
RECOVERY_CODE_COUNT: Final = 10
RECOVERY_CODE_GROUP_LENGTH: Final = 4
_MAX_GENERATION_ATTEMPTS: Final = 100


class RecoveryCodeError(ValueError):
    """Raised when recovery-code generation cannot produce a safe batch."""


@dataclass(frozen=True)
class GeneratedRecoveryCode:
    """A one-time display value paired with its persistence-safe digest."""

    display_value: str
    lookup_digest: bytes


class RecoveryCodeService:
    """Generate and validate recovery codes without consuming any credential."""

    def __init__(
        self,
        *,
        secret_generator: SecretGenerator,
        protector: RecoveryCodeProtector,
    ) -> None:
        self._secret_generator = secret_generator
        self._protector = protector
        self.key_version = protector.key_version

    def generate(self) -> tuple[GeneratedRecoveryCode, ...]:
        """Return exactly ten unique display values and their HMAC digests.

        Callers must persist only the digests and show display values only after
        their surrounding successful transaction commits.
        """

        generated: list[GeneratedRecoveryCode] = []
        normalized_values: set[str] = set()
        attempts = 0
        while len(generated) < RECOVERY_CODE_COUNT:
            attempts += 1
            if attempts > _MAX_GENERATION_ATTEMPTS:
                raise RecoveryCodeError("recovery code entropy is not unique.")
            normalized_value = self._generate_normalized_value()
            if normalized_value in normalized_values:
                continue
            normalized_values.add(normalized_value)
            generated.append(
                GeneratedRecoveryCode(
                    display_value=format_recovery_code(normalized_value),
                    lookup_digest=self._protector.digest(normalized_value),
                )
            )
        return tuple(generated)

    def match(
        self,
        *,
        value: str,
        active_lookup_digests: Collection[bytes],
    ) -> bytes | None:
        """Return a matching active digest without marking it as used."""

        normalized_value = normalize_recovery_code(value)
        if normalized_value is None:
            return None
        candidate = self._protector.digest(normalized_value)
        for active_digest in active_lookup_digests:
            if isinstance(active_digest, bytes) and hmac.compare_digest(
                candidate, active_digest
            ):
                return candidate
        return None

    def _generate_normalized_value(self) -> str:
        entropy = self._secret_generator.token_bytes(RECOVERY_CODE_LENGTH)
        if not isinstance(entropy, bytes) or len(entropy) != RECOVERY_CODE_LENGTH:
            raise RecoveryCodeError("recovery code entropy is invalid.")
        return "".join(RECOVERY_CODE_ALPHABET[value & 0x1F] for value in entropy)


def normalize_recovery_code(value: str) -> str | None:
    """Normalize exactly the approved display variations of one code."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("-", "").upper()
    if (
        len(normalized) != RECOVERY_CODE_LENGTH
        or any(character not in RECOVERY_CODE_ALPHABET for character in normalized)
    ):
        return None
    return normalized


def format_recovery_code(normalized_value: str) -> str:
    """Format a normalized recovery code as four visual groups."""

    if normalize_recovery_code(normalized_value) != normalized_value:
        raise RecoveryCodeError("recovery code is invalid.")
    return "-".join(
        normalized_value[index : index + RECOVERY_CODE_GROUP_LENGTH]
        for index in range(0, RECOVERY_CODE_LENGTH, RECOVERY_CODE_GROUP_LENGTH)
    )
