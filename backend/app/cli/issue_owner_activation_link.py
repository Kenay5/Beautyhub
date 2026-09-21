"""Authorized command that issues or reissues the initial owner activation link."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from backend.app.application.admin_access.owner_activation_link import (
    DeliverOwnerActivationLink,
    OwnerActivationLinkError,
    PrepareOwnerActivationLink,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.owner_activation_link_repository import (
    PostgresOwnerActivationRecipientStore,
)
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.sanitized_observability import log_security_event
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.settings import (
    ConfigurationError,
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.web.admin_auth.security_link_transport import security_link_fragment


INITIAL_ACTIVATION_LINK_PATH = "/admin/security-link"


def parse_command_arguments(arguments: Sequence[str] | None = None) -> None:
    """Accept no token or email arguments; both remain outside shell history."""

    parser = argparse.ArgumentParser(
        description="Issue the initial BeautyHub owner activation link."
    )
    parser.parse_args(arguments)


def main(
    arguments: Sequence[str] | None = None,
    *,
    output: TextIO = sys.stdout,
    error_output: TextIO = sys.stderr,
) -> int:
    """Create a fresh 30-minute link and send it only to the stored owner email."""

    parse_command_arguments(arguments)
    try:
        settings = load_settings()
        key_configuration = load_cryptography_key_configuration()
        engine = create_postgres_engine(settings.database_url)
    except ConfigurationError:
        print("Owner activation link is unavailable.", file=error_output)
        return 1

    clock = SystemClock()
    key_ring = CryptographyKeyRing(key_configuration)
    email_protector = AdministrativeEmailProtector(
        key_ring=key_ring,
        secret_generator=SystemSecretGenerator(),
    )
    try:
        with engine.begin() as connection:
            prepared_link = PrepareOwnerActivationLink(
                recipient_store=PostgresOwnerActivationRecipientStore(
                    connection,
                    email_protector=email_protector,
                ),
                link_lifecycle=SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=clock,
                    secret_generator=SystemSecretGenerator(),
                    protector=SecurityLinkProtector(key_ring=key_ring),
                ),
            ).prepare()

        with engine.begin() as connection:
            delivery_accepted = DeliverOwnerActivationLink(
                delivery_state_store=PostgresSecurityLinkStore(connection),
                email_sender=EmailSimulator(outcome="accepted"),
                clock=clock,
            ).deliver(
                prepared_link=prepared_link,
                content=(
                    INITIAL_ACTIVATION_LINK_PATH
                    + security_link_fragment(prepared_link.issued_link.token)
                ),
            )
    except OwnerActivationLinkError:
        print("Owner activation link is unavailable.", file=error_output)
        return 1
    finally:
        engine.dispose()

    if not delivery_accepted:
        log_security_event(event="security_link_delivery_failed", outcome="failed")
        print("Owner activation link could not be sent.", file=error_output)
        return 1

    print("Owner activation link issued.", file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
