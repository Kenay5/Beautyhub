"""Owner-only forced staff password-reset contract."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import AdministrativeActor, AdministrativeAuthorizationError
from backend.app.application.admin_access.force_staff_password_reset import ForceStaffPasswordReset, ForcedPasswordReset
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import EMAIL_CHANNEL, OutboundNotification, TransactionalNotificationPort
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.force_staff_password_reset_repository import PostgresForceStaffPasswordResetStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration, load_settings
from backend.app.web.admin_auth.mutation_protection import require_administrative_mutation_protection
from backend.app.web.admin_auth.security_link_transport import security_link_fragment
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor


router = APIRouter(prefix="/api/admin/staff-password-reset", tags=["admin-staff-password-reset"])
_FORBIDDEN_DETAIL = "No tienes permiso para realizar esta operación."
_UNAVAILABLE_DETAIL = "No fue posible iniciar el restablecimiento de contraseña."
_LOGGER = logging.getLogger(__name__)


class ForcedPasswordResetResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    delivery_status: Literal["accepted", "failed"] = Field(serialization_alias="deliveryStatus")
    detail: str | None = None


class ForcedPasswordResetOperations(Protocol):
    def force(self, *, actor: AdministrativeActor) -> ForcedPasswordResetResponse: ...


class PostgresForcedPasswordResetOperations:
    """Commit credential/session invalidation before the provider delivery."""

    def __init__(self, *, engine: Engine, email_sender: TransactionalNotificationPort | None = None) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")
        self._clock = SystemClock()
        self._key_ring = CryptographyKeyRing(load_cryptography_key_configuration())

    def force(self, *, actor: AdministrativeActor) -> ForcedPasswordResetResponse:
        entropy = SystemSecretGenerator()
        email_protector = AdministrativeEmailProtector(key_ring=self._key_ring, secret_generator=entropy)
        link_protector = SecurityLinkProtector(key_ring=self._key_ring)
        with self._engine.begin() as connection:
            reset = ForceStaffPasswordReset(
                store=PostgresForceStaffPasswordResetStore(
                    connection,
                    email_protector=email_protector,
                    current_time=self._clock.now(),
                ),
                link_lifecycle=SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=self._clock,
                    secret_generator=entropy,
                    protector=link_protector,
                ),
                audit=RecordAdministrativeAuditEvent(
                    store=PostgresAdministrativeAuditStore(connection), clock=self._clock
                ),
            ).force(actor=actor)

        content = (
            "El propietario de tu cuenta solicitó que establezcas una contraseña nueva. "
            "Este enlace es válido durante 30 minutos: /admin/password-recovery"
            + security_link_fragment(reset.issued_link.token)
        )
        try:
            sent = self._email_sender.send(
                OutboundNotification(channel=EMAIL_CHANNEL, recipient=reset.recipient_email, content=content)
            )
        except Exception:
            _LOGGER.warning("forced staff password reset delivery failed")
            self._record_failed_delivery(reset)
            return ForcedPasswordResetResponse(
                delivery_status="failed",
                detail="No se pudo enviar el enlace. La contraseña anterior ya no permite iniciar sesión. Puedes emitir un enlace nuevo.",
            )

        if sent.channel != EMAIL_CHANNEL or sent.outcome != "accepted":
            self._record_failed_delivery(reset)
            return ForcedPasswordResetResponse(
                delivery_status="failed",
                detail="No se pudo enviar el enlace. La contraseña anterior ya no permite iniciar sesión. Puedes emitir un enlace nuevo.",
            )
        with self._engine.begin() as connection:
            PostgresSecurityLinkStore(connection).mark_delivery_accepted(
                link_id=reset.issued_link.stored_link.link_id,
                current_time=self._clock.now(),
            )
        return ForcedPasswordResetResponse(delivery_status="accepted")

    def _record_failed_delivery(self, reset: ForcedPasswordReset) -> None:
        with self._engine.begin() as connection:
            now = self._clock.now()
            PostgresSecurityLinkStore(connection).invalidate_failed_delivery(
                link_id=reset.issued_link.stored_link.link_id,
                current_time=now,
            )
            RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection), clock=self._clock
            ).record(
                actor_account_id=reset.owner_account_id,
                action="password_recovery",
                result="failed",
                target_reference=f"admin_account:{reset.staff_account_id}",
            )


def get_forced_password_reset_operations() -> Iterator[ForcedPasswordResetOperations]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield PostgresForcedPasswordResetOperations(engine=engine)
    finally:
        engine.dispose()


@router.post("", response_model=ForcedPasswordResetResponse)
def force_staff_password_reset(
    protection: Annotated[None, Depends(require_administrative_mutation_protection, scope="function")],
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operations: Annotated[ForcedPasswordResetOperations, Depends(get_forced_password_reset_operations)],
) -> ForcedPasswordResetResponse:
    del protection
    try:
        return operations.force(actor=actor)
    except AdministrativeAuthorizationError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL) from error
    except (ValueError, LookupError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_UNAVAILABLE_DETAIL) from error
