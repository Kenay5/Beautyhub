"""Fail-safe local membership checks for compromised administrative passwords."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from backend.app.application.clock import Clock
from backend.app.domain.time import to_business_time


BLOCKED_PASSWORDS_FILENAME = "blocked_passwords.sha1"
BLOCKED_PASSWORDS_METADATA_FILENAME = "blocked_passwords.metadata.json"
BLOCKED_PASSWORDS_ENTRY_COUNT = 1_000
SHA1_PATTERN = re.compile(r"[0-9A-F]{40}")
SHA256_PATTERN = re.compile(r"[0-9A-F]{64}")
DEFAULT_BLOCKED_PASSWORDS_RESOURCE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "resources"
)


class BlockedPasswordListError(ValueError):
    """Raised when the required local list cannot be used safely."""


class BlockedPasswordList:
    """Validated local SHA-1 membership list that never normalizes a password."""

    def __init__(
        self,
        *,
        hashes: frozenset[str],
        review_due: date,
        clock: Clock,
    ) -> None:
        self._hashes = hashes
        self._review_due = review_due
        self._clock = clock

    @classmethod
    def load(
        cls,
        *,
        resource_directory: Path = DEFAULT_BLOCKED_PASSWORDS_RESOURCE_DIRECTORY,
        clock: Clock,
    ) -> "BlockedPasswordList":
        """Load and verify the committed artifact before it may protect a password."""

        file_path = resource_directory / BLOCKED_PASSWORDS_FILENAME
        metadata_path = resource_directory / BLOCKED_PASSWORDS_METADATA_FILENAME
        try:
            content = file_path.read_bytes()
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BlockedPasswordListError("blocked password list is unavailable.") from error

        review_due = _validate_metadata(metadata=metadata, content=content)
        hashes = _validate_hashes(content)
        return cls(hashes=hashes, review_due=review_due, clock=clock)

    def contains(self, password: str) -> bool:
        """Check the exact UTF-8 password only while the verified list is current."""

        if not isinstance(password, str):
            raise BlockedPasswordListError("blocked password lookup is invalid.")
        if self._business_today() >= self._review_due:
            raise BlockedPasswordListError("blocked password list review is overdue.")
        password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        return password_hash in self._hashes

    def _business_today(self) -> date:
        return to_business_time(self._clock.now()).date()


def _validate_metadata(*, metadata: Any, content: bytes) -> date:
    if not isinstance(metadata, dict):
        raise BlockedPasswordListError("blocked password metadata is invalid.")
    if metadata.get("entry_count") != BLOCKED_PASSWORDS_ENTRY_COUNT:
        raise BlockedPasswordListError("blocked password metadata is invalid.")

    checksum = metadata.get("sha256")
    if not isinstance(checksum, str) or not SHA256_PATTERN.fullmatch(checksum):
        raise BlockedPasswordListError("blocked password metadata is invalid.")
    actual_checksum = hashlib.sha256(content).hexdigest().upper()
    if actual_checksum != checksum:
        raise BlockedPasswordListError("blocked password list checksum is invalid.")

    review_due = metadata.get("review_due")
    if not isinstance(review_due, str):
        raise BlockedPasswordListError("blocked password metadata is invalid.")
    try:
        return date.fromisoformat(review_due)
    except ValueError as error:
        raise BlockedPasswordListError("blocked password metadata is invalid.") from error


def _validate_hashes(content: bytes) -> frozenset[str]:
    try:
        lines = content.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise BlockedPasswordListError("blocked password list is invalid.") from error

    if len(lines) != BLOCKED_PASSWORDS_ENTRY_COUNT:
        raise BlockedPasswordListError("blocked password list is invalid.")
    if any(SHA1_PATTERN.fullmatch(item) is None for item in lines):
        raise BlockedPasswordListError("blocked password list is invalid.")
    hashes = frozenset(lines)
    if len(hashes) != BLOCKED_PASSWORDS_ENTRY_COUNT:
        raise BlockedPasswordListError("blocked password list is invalid.")
    return hashes
