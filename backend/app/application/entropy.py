"""Cryptographic entropy ports and deterministic test doubles."""

from __future__ import annotations

import secrets
from collections import deque
from collections.abc import Iterable
from typing import Protocol


class SecretGenerator(Protocol):
    """Generate opaque bytes for future private codes and references."""

    def token_bytes(self, size: int) -> bytes:
        """Return exactly ``size`` cryptographically suitable bytes."""


def _validate_size(size: int) -> None:
    if size <= 0:
        raise ValueError("Secret size must be greater than zero.")


class SystemSecretGenerator:
    """Use Python's cryptographically secure source of randomness."""

    def token_bytes(self, size: int) -> bytes:
        _validate_size(size)
        return secrets.token_bytes(size)


class SequenceSecretGenerator:
    """Return predefined bytes in order for deterministic tests."""

    def __init__(self, tokens: Iterable[bytes]) -> None:
        self._tokens = deque(tokens)

    def token_bytes(self, size: int) -> bytes:
        _validate_size(size)

        if not self._tokens:
            raise RuntimeError("No deterministic secret is available.")

        token = self._tokens[0]
        if len(token) != size:
            raise ValueError("The deterministic secret does not match the requested size.")

        return self._tokens.popleft()
