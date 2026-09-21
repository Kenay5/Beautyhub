"""Clock ports and implementations for deterministic temporal rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Provide the current absolute instant to application and domain rules."""

    def now(self) -> datetime:
        """Return an aware datetime."""


class SystemClock:
    """Read the current instant in UTC from the operating system clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FixedClock:
    """Return one controlled instant for deterministic tests."""

    instant: datetime

    def __post_init__(self) -> None:
        if self.instant.tzinfo is None or self.instant.utcoffset() is None:
            raise ValueError("A fixed clock requires an aware datetime.")

    def now(self) -> datetime:
        return self.instant
