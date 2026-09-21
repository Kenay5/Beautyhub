"""Interactive command for the one protected owner bootstrap registration."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from sqlalchemy.exc import IntegrityError

from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.admin_access.owner_bootstrap import RegisterOwnerBootstrap
from backend.app.domain.authentication.admin_email_claim import (
    AdministrativeEmailClaimError,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.owner_bootstrap_repository import (
    OwnerBootstrapRegistrationError,
    PostgresOwnerBootstrapRegistrationStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    ConfigurationError,
    load_cryptography_key_configuration,
    load_settings,
)


def parse_command_arguments(arguments: Sequence[str] | None = None) -> None:
    """Accept no email argument so the command always prompts interactively."""

    parser = argparse.ArgumentParser(
        description="Register the initial BeautyHub owner email interactively."
    )
    parser.parse_args(arguments)


def main(
    arguments: Sequence[str] | None = None,
    *,
    input_function: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    error_output: TextIO = sys.stderr,
) -> int:
    """Prompt for one email and create only the inactive owner identity."""

    parse_command_arguments(arguments)
    try:
        email = input_function("Owner email: ")
    except EOFError:
        print("Owner registration was cancelled.", file=error_output)
        return 2

    try:
        settings = load_settings()
        key_configuration = load_cryptography_key_configuration()
        engine = create_postgres_engine(settings.database_url)
    except ConfigurationError:
        print("Owner registration is unavailable.", file=error_output)
        return 1

    try:
        with engine.begin() as connection:
            RegisterOwnerBootstrap(
                store=PostgresOwnerBootstrapRegistrationStore(connection),
                email_protector=AdministrativeEmailProtector(
                    key_ring=CryptographyKeyRing(key_configuration),
                    secret_generator=SystemSecretGenerator(),
                ),
            ).register(email=email)
    except (
        AdministrativeEmailClaimError,
        IntegrityError,
        OwnerBootstrapRegistrationError,
    ):
        print("Owner registration is unavailable.", file=error_output)
        return 1
    finally:
        engine.dispose()

    print("Owner registration completed.", file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
