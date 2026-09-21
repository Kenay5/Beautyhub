"""PostgreSQL reader for exact public appointment-code lookup."""

from __future__ import annotations

from backend.app.application.lookup_public_appointment import (
    PublicAppointmentLookupReader,
    PublicAppointmentRecord,
)
from backend.app.infrastructure.persistence.models import Appointment
from sqlalchemy import Connection, select


class PostgresPublicAppointmentLookupReader(PublicAppointmentLookupReader):
    """Read the public appointment projection for one private-code digest."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def find_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> PublicAppointmentRecord | None:
        """Select only the record whose protected lookup value matches exactly."""

        row = self._connection.execute(
            select(
                Appointment.service_snapshot_name,
                Appointment.service_snapshot_duration_minutes,
                Appointment.service_snapshot_price,
                Appointment.branch,
                Appointment.scheduled_start,
                Appointment.status,
                Appointment.phone,
                Appointment.email,
            ).where(Appointment.private_code_digest == private_code_digest)
        ).one_or_none()
        if row is None:
            return None

        return PublicAppointmentRecord(
            service_name=row.service_snapshot_name,
            duration_minutes=row.service_snapshot_duration_minutes,
            price=row.service_snapshot_price,
            branch=row.branch,
            scheduled_start=row.scheduled_start,
            status=row.status,
            phone=row.phone,
            email=row.email,
        )
