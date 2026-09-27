"""Owner-only HTTP endpoints for reviewing and deactivating staff access."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.admin_access.staff_deactivation import (
    DeactivateStaff,
    StaffDeactivationError,
    StaffStatus,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.infrastructure.email_simulator import (
    EmailSimulator,
    EmailSimulatorUncertainOutcome,
)
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.persistence.staff_deactivation_repository import (
    PostgresStaffDeactivationStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor


router = APIRouter(prefix="/api/admin/staff", tags=["admin-staff-deactivation"])
_LOGGER = logging.getLogger(__name__)
_FORBIDDEN_DETAIL = "No tienes permiso para realizar esta operación."
_UNAVAILABLE_DETAIL = "No fue posible actualizar el acceso del personal."
_NOTICE = (
    "Se desactivó una cuenta de personal. Para autorizar nuevamente a esa persona, "
    "deberás enviar una nueva invitación."
)


class StaffStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    status: Literal["none", "pending", "active"]


class StaffDeactivationOperations(Protocol):
    def status(self, *, actor: AdministrativeActor) -> StaffStatus: ...
    def deactivate(self, *, actor: AdministrativeActor) -> None: ...


class PostgresStaffDeactivationOperations:
    def __init__(
        self,
        *,
        engine: Engine,
        email_sender: TransactionalNotificationPort | None = None,
    ) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")
        self._clock = SystemClock()
        self._key_ring = CryptographyKeyRing(load_cryptography_key_configuration())

    def status(self, *, actor: AdministrativeActor) -> StaffStatus:
        with self._engine.begin() as connection:
            return self._compose(connection).status(actor=actor)

    def deactivate(self, *, actor: AdministrativeActor) -> None:
        with self._engine.begin() as connection:
            result = self._compose(connection).deactivate(actor=actor)
        try:
            sent = self._email_sender.send(
                OutboundNotification(
                    channel=EMAIL_CHANNEL,
                    recipient=result.owner_email,
                    content=_NOTICE,
                )
            )
            delivery_outcome = sent.outcome if sent.channel == EMAIL_CHANNEL else "failed"
        except EmailSimulatorUncertainOutcome:
            delivery_outcome = "uncertain"
        except Exception:
            delivery_outcome = "failed"
        try:
            with self._engine.begin() as connection:
                PostgresSecurityNotificationDeliveryStore(connection).record_immediate_result(
                    delivery_id=result.notification_delivery_id,
                    outcome=delivery_outcome,
                )
        except Exception:
            _LOGGER.error("staff deactivation notice status was not recorded")

    def _compose(self, connection: Connection) -> DeactivateStaff:
        entropy = SystemSecretGenerator()
        return DeactivateStaff(
            store=PostgresStaffDeactivationStore(
                connection,
                email_protector=AdministrativeEmailProtector(
                    key_ring=self._key_ring,
                    secret_generator=entropy,
                ),
            ),
            audit=RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=self._clock,
            ),
            notifications=RecordSecurityNotificationDelivery(
                store=PostgresSecurityNotificationDeliveryStore(connection),
                protector=SecurityNotificationDeliveryProtector(
                    key_ring=self._key_ring,
                    secret_generator=entropy,
                ),
            ),
            clock=self._clock,
        )


def get_staff_deactivation_operations() -> Iterator[StaffDeactivationOperations]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield PostgresStaffDeactivationOperations(engine=engine)
    finally:
        engine.dispose()


def _translate(error: Exception) -> HTTPException:
    if isinstance(error, AdministrativeAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_UNAVAILABLE_DETAIL)


@router.get("/current", response_model=StaffStatusResponse)
def load_staff_status(
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operations: Annotated[StaffDeactivationOperations, Depends(get_staff_deactivation_operations)],
) -> StaffStatusResponse:
    try:
        return StaffStatusResponse(status=operations.status(actor=actor))
    except (AdministrativeAuthorizationError, StaffDeactivationError, ValueError) as error:
        raise _translate(error) from error


@router.post("/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_staff(
    response: Response,
    protection: Annotated[
        None,
        Depends(require_administrative_mutation_protection, scope="function"),
    ],
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operations: Annotated[StaffDeactivationOperations, Depends(get_staff_deactivation_operations)],
) -> None:
    del protection
    response.headers["Cache-Control"] = "no-store"
    try:
        operations.deactivate(actor=actor)
    except (AdministrativeAuthorizationError, StaffDeactivationError, ValueError) as error:
        raise _translate(error) from error
