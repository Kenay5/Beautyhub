"""PostgreSQL reader for the currently valid public privacy notice."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, or_, select

from backend.app.application.get_current_privacy_notice import CurrentPrivacyNotice
from backend.app.infrastructure.persistence.models import PrivacyNoticeVersion


class PostgresCurrentPrivacyNoticeReader:
    """Read one public privacy notice without exposing its internal identifier."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_current_privacy_notice(
        self, *, at: datetime
    ) -> CurrentPrivacyNotice | None:
        """Return the one notice whose validity period contains ``at``."""

        row = self._connection.execute(
            select(PrivacyNoticeVersion.version, PrivacyNoticeVersion.content)
            .where(
                PrivacyNoticeVersion.valid_from <= at,
                or_(
                    PrivacyNoticeVersion.valid_until.is_(None),
                    PrivacyNoticeVersion.valid_until > at,
                ),
            )
            .order_by(PrivacyNoticeVersion.valid_from.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return CurrentPrivacyNotice(version=row.version, content=row.content)
