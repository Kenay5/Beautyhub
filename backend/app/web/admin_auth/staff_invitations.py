"""Owner-only HTTP contract for the single pending staff invitation."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.staff_invitation import (
    CreateStaffInvitation,
    DeliverStaffInvitation,
    ManageStaffInvitation,
    StaffInvitationDeliveryOutcome,
    StaffInvitationError,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import (
    TransactionalNotificationPort,
)
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.persistence.staff_invitation_repository import (
    PostgresStaffInvitationStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.web.admin_auth.security_link_transport import security_link_fragment
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor


router = APIRouter(prefix="/api/admin/staff-invitations", tags=["admin-staff-invitations"])
_FORBIDDEN_DETAIL = "No tienes permiso para realizar esta operación."
_UNAVAILABLE_DETAIL = "No fue posible actualizar la invitación."


class StaffInvitationBody(BaseModel):
    email: str = Field(min_length=1, max_length=254)


class StaffInvitationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str = "pending"
    delivery_status: str = Field(serialization_alias="deliveryStatus")
    detail: str | None = None


class StaffInvitationOperations(Protocol):
    def invite(self, *, actor: AdministrativeActor, email: str) -> StaffInvitationDeliveryOutcome: ...
    def resend(self, *, actor: AdministrativeActor) -> StaffInvitationDeliveryOutcome: ...
    def cancel(self, *, actor: AdministrativeActor) -> None: ...


class PostgresStaffInvitationOperations:
    """Coordinate committed invitation state and the separate delivery attempt."""

    def __init__(
        self,
        *,
        engine: Engine,
        email_sender: TransactionalNotificationPort | None = None,
    ) -> None:
        self._engine = engine
        self._email_sender = email_sender
        self._clock = SystemClock()
        self._key_ring = CryptographyKeyRing(load_cryptography_key_configuration())

    def invite(self, *, actor: AdministrativeActor, email: str) -> StaffInvitationDeliveryOutcome:
        with self._engine.begin() as connection:
            invitation = CreateStaffInvitation(
                store=PostgresStaffInvitationStore(connection),
                email_protector=self._email_protector(),
                link_lifecycle=self._link_lifecycle(connection),
                audit=self._audit(connection),
            ).invite(actor=actor, email=email)
        return self._deliver(invitation)

    def resend(self, *, actor: AdministrativeActor) -> StaffInvitationDeliveryOutcome:
        with self._engine.begin() as connection:
            invitation = ManageStaffInvitation(
                store=PostgresStaffInvitationStore(
                    connection,
                    email_protector=self._email_protector(),
                ),
                link_lifecycle=self._link_lifecycle(connection),
                audit=self._audit(connection),
                clock=self._clock,
            ).resend(actor=actor)
        return self._deliver(invitation)

    def cancel(self, *, actor: AdministrativeActor) -> None:
        with self._engine.begin() as connection:
            ManageStaffInvitation(
                store=PostgresStaffInvitationStore(
                    connection,
                    email_protector=self._email_protector(),
                ),
                link_lifecycle=self._link_lifecycle(connection),
                audit=self._audit(connection),
                clock=self._clock,
            ).cancel(actor=actor)

    def _deliver(self, invitation) -> StaffInvitationDeliveryOutcome:
        content = "/admin/staff-activation" + security_link_fragment(
            invitation.issued_link.token
        )
        with self._engine.begin() as connection:
            return DeliverStaffInvitation(
                delivery_state_store=PostgresSecurityLinkStore(connection),
                email_sender=self._email_sender or EmailSimulator(outcome="accepted"),
                audit=self._audit(connection),
                clock=self._clock,
            ).deliver(invitation=invitation, content=content)

    def _link_lifecycle(self, connection) -> SecurityLinkLifecycle:
        return SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=self._clock,
            secret_generator=SystemSecretGenerator(),
            protector=SecurityLinkProtector(key_ring=self._key_ring),
        )

    def _email_protector(self) -> AdministrativeEmailProtector:
        return AdministrativeEmailProtector(
            key_ring=self._key_ring,
            secret_generator=SystemSecretGenerator(),
        )

    def _audit(self, connection) -> RecordAdministrativeAuditEvent:
        return RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection),
            clock=self._clock,
        )


def get_staff_invitation_operations() -> Iterator[StaffInvitationOperations]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield PostgresStaffInvitationOperations(engine=engine)
    finally:
        engine.dispose()


def _response(outcome: StaffInvitationDeliveryOutcome) -> StaffInvitationResponse:
    return StaffInvitationResponse(
        delivery_status="accepted" if outcome.accepted else "failed",
        detail=outcome.detail,
    )


def _translate(error: Exception) -> HTTPException:
    if isinstance(error, AdministrativeAuthorizationError):
        return HTTPException(status_code=403, detail=_FORBIDDEN_DETAIL)
    return HTTPException(status_code=409, detail=_UNAVAILABLE_DETAIL)


@router.post("", response_model=StaffInvitationResponse, status_code=status.HTTP_201_CREATED)
def invite_staff(
    body: StaffInvitationBody,
    protection: Annotated[
        None,
        Depends(require_administrative_mutation_protection, scope="function"),
    ],
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operations: Annotated[StaffInvitationOperations, Depends(get_staff_invitation_operations)],
) -> StaffInvitationResponse:
    del protection
    try:
        return _response(operations.invite(actor=actor, email=body.email))
    except (AdministrativeAuthorizationError, StaffInvitationError, ValueError) as error:
        raise _translate(error) from error


@router.post("/resend", response_model=StaffInvitationResponse)
def resend_staff_invitation(
    protection: Annotated[
        None,
        Depends(require_administrative_mutation_protection, scope="function"),
    ],
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operations: Annotated[StaffInvitationOperations, Depends(get_staff_invitation_operations)],
) -> StaffInvitationResponse:
    del protection
    try:
        return _response(operations.resend(actor=actor))
    except (AdministrativeAuthorizationError, StaffInvitationError, ValueError) as error:
        raise _translate(error) from error


@router.post("/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_staff_invitation(
    protection: Annotated[
        None,
        Depends(require_administrative_mutation_protection, scope="function"),
    ],
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operations: Annotated[StaffInvitationOperations, Depends(get_staff_invitation_operations)],
) -> None:
    del protection
    try:
        operations.cancel(actor=actor)
    except (AdministrativeAuthorizationError, StaffInvitationError, ValueError) as error:
        raise _translate(error) from error
