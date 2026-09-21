"""HTTP composition for public-request abuse protection."""

from __future__ import annotations

from collections.abc import Iterator
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address

from fastapi import Request

from backend.app.application.clock import SystemClock
from backend.app.application.public_access_restrictions import (
    CombinePublicAppointmentRestrictions,
    ProtectPublicAppointmentLookup,
)
from backend.app.application.public_credential_failures import (
    RecordPublicCredentialFailure,
)
from backend.app.application.public_request_limit import (
    AllowPublicRequests,
    LimitPublicAppointmentRequests,
    LimitPublicReadRequests,
    PublicRequestLimiter,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.public_request_limit_repository import (
    PostgresPublicRequestWindowStore,
)
from backend.app.infrastructure.persistence.public_credential_failure_repository import (
    PostgresPublicCredentialFailureStore,
)
from backend.app.infrastructure.security.public_request_subject import (
    PublicRequestSubjectProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
    load_trusted_proxy_networks,
)


def get_public_request_limiter() -> PublicRequestLimiter:
    """Provide the public request guard until T068 persists approved windows."""

    return AllowPublicRequests()


def get_public_read_request_limiter(request: Request) -> Iterator[PublicRequestLimiter]:
    """Build the persisted limiter for catalog and availability only."""

    subject_fingerprint = _public_request_subject_fingerprint(request)
    engine = create_postgres_engine(load_settings().database_url)
    try:
        with engine.begin() as connection:
            yield LimitPublicReadRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=SystemClock(),
                subject_fingerprint=subject_fingerprint,
            )
    finally:
        engine.dispose()


def get_public_appointment_operation_limiter(
    request: Request,
) -> Iterator[PublicRequestLimiter]:
    """Build the persisted limiter for public appointment operations only."""

    subject_fingerprint = _public_request_subject_fingerprint(request)
    engine = create_postgres_engine(load_settings().database_url)
    try:
        with engine.begin() as connection:
            yield LimitPublicAppointmentRequests(
                store=PostgresPublicRequestWindowStore(connection),
                clock=SystemClock(),
                subject_fingerprint=subject_fingerprint,
            )
    finally:
        engine.dispose()


def get_public_appointment_lookup_protection(
    request: Request,
) -> Iterator[ProtectPublicAppointmentLookup]:
    """Compose lookup protection in one short PostgreSQL transaction."""

    yield from _public_appointment_credential_protection(
        request,
        operation_category="appointment_lookup",
    )


def get_public_appointment_modification_protection(
    request: Request,
) -> Iterator[ProtectPublicAppointmentLookup]:
    """Compose shared credential protection under the modification category."""

    yield from _public_appointment_credential_protection(
        request,
        operation_category="appointment_modification",
    )


def get_public_appointment_cancellation_protection(
    request: Request,
) -> Iterator[ProtectPublicAppointmentLookup]:
    """Compose shared credential protection under the cancellation category."""

    yield from _public_appointment_credential_protection(
        request,
        operation_category="appointment_cancellation",
    )


def _public_appointment_credential_protection(
    request: Request,
    *,
    operation_category: str,
) -> Iterator[ProtectPublicAppointmentLookup]:
    """Open one short transaction for a public credential-bearing operation."""

    subject_fingerprint = _public_request_subject_fingerprint(request)
    engine = create_postgres_engine(load_settings().database_url)
    try:
        with engine.begin() as connection:
            clock = SystemClock()
            request_store = PostgresPublicRequestWindowStore(connection)
            credential_store = PostgresPublicCredentialFailureStore(connection)
            yield ProtectPublicAppointmentLookup(
                restrictions=CombinePublicAppointmentRestrictions(
                    request_store=request_store,
                    credential_store=credential_store,
                    clock=clock,
                    subject_fingerprint=subject_fingerprint,
                ),
                failure_recorder=RecordPublicCredentialFailure(
                    store=credential_store,
                    clock=clock,
                ),
                subject_fingerprint=subject_fingerprint,
                operation_category=operation_category,
            )
    finally:
        engine.dispose()


def _public_request_subject_fingerprint(request: Request) -> bytes:
    direct_host = request.client.host if request.client is not None else ""
    client_ip = resolve_public_client_ip(
        direct_host=direct_host,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_proxy_networks=load_trusted_proxy_networks(),
    )
    return PublicRequestSubjectProtector(
        key_ring=CryptographyKeyRing(load_cryptography_key_configuration())
    ).fingerprint_ip(client_ip)


def resolve_public_client_ip(
    *,
    direct_host: str,
    forwarded_for: str | None,
    trusted_proxy_networks: tuple[IPv4Network | IPv6Network, ...],
) -> str:
    """Use forwarded addresses only when the direct peer is explicitly trusted."""

    direct_address = _parse_ip(direct_host)
    if not _is_trusted(direct_address, trusted_proxy_networks) or not forwarded_for:
        return direct_address.compressed

    try:
        forwarded_addresses = tuple(
            _parse_ip(value.strip()) for value in forwarded_for.split(",")
        )
    except ValueError:
        return direct_address.compressed

    for address in reversed(forwarded_addresses):
        if not _is_trusted(address, trusted_proxy_networks):
            return address.compressed
    return direct_address.compressed


def _parse_ip(value: str) -> IPv4Address | IPv6Address:
    if not value:
        raise ValueError("public request client address is unavailable.")
    return ip_address(value)


def _is_trusted(
    address: IPv4Address | IPv6Address,
    networks: tuple[IPv4Network | IPv6Network, ...],
) -> bool:
    return any(
        address.version == network.version and address in network
        for network in networks
    )
