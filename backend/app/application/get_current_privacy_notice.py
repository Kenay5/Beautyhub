"""Read the current privacy notice without depending on delivery or storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.application.clock import Clock


@dataclass(frozen=True)
class CurrentPrivacyNotice:
    """The public fields required to obtain informed consent."""

    version: str
    content: str


class CurrentPrivacyNoticeReader(Protocol):
    """Read the notice valid at a supplied instant."""

    def get_current_privacy_notice(
        self, *, at: datetime
    ) -> CurrentPrivacyNotice | None:
        """Return the single current notice, if one exists."""


class GetCurrentPrivacyNotice:
    """Resolve the privacy notice visible to a public reservation."""

    def __init__(self, reader: CurrentPrivacyNoticeReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock

    def execute(self) -> CurrentPrivacyNotice | None:
        """Read only the version and content that are currently valid."""

        return self._reader.get_current_privacy_notice(at=self._clock.now())
