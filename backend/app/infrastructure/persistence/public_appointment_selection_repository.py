"""Read the current public choices needed to confirm an appointment."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, or_, select

from backend.app.application.confirm_public_appointment import (
    PublicAppointmentSelectionReader,
)
from backend.app.infrastructure.persistence.models import PrivacyNoticeVersion, Service


class PostgresPublicAppointmentSelectionReader(PublicAppointmentSelectionReader):
    """Resolve public names and notice versions without returning internal IDs."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_active_service_id(self, *, branch: str, service_name: str) -> int | None:
        """Find exactly one active service offered by the selected branch."""

        availability_column = (
            Service.available_chiconcuac
            if branch == "chiconcuac"
            else Service.available_texcoco
        )
        return self._connection.execute(
            select(Service.service_id).where(
                Service.canonical_name == service_name.lower(),
                Service.is_active.is_(True),
                availability_column.is_(True),
            )
        ).scalar_one_or_none()

    def get_current_privacy_notice_version_id(
        self,
        *,
        version: str,
        accepted_at: datetime,
    ) -> int | None:
        """Resolve only a version valid when the server records acceptance."""

        return self._connection.execute(
            select(PrivacyNoticeVersion.privacy_notice_version_id).where(
                PrivacyNoticeVersion.version == version,
                PrivacyNoticeVersion.valid_from <= accepted_at,
                or_(
                    PrivacyNoticeVersion.valid_until.is_(None),
                    PrivacyNoticeVersion.valid_until > accepted_at,
                ),
            )
        ).scalar_one_or_none()
