"""External runtime configuration with redacted sensitive values."""

from __future__ import annotations

import os
import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_network
from sqlalchemy.engine import make_url
from urllib.parse import urlsplit


DATABASE_URL_ENVIRONMENT_VARIABLE = "BEAUTYHUB_DATABASE_URL"
TEST_DATABASE_URL_ENVIRONMENT_VARIABLE = "BEAUTYHUB_TEST_DATABASE_URL"
PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE = "BEAUTYHUB_PRIVATE_CODE_MASTER_KEY"
CRYPTOGRAPHY_KEY_VERSION_ENVIRONMENT_VARIABLE = "BEAUTYHUB_CRYPTOGRAPHY_KEY_VERSION"
TRUSTED_PROXY_CIDRS_ENVIRONMENT_VARIABLE = "BEAUTYHUB_TRUSTED_PROXY_CIDRS"
TEST_DATABASE_NAME = "beautyhub_test"
POSTGRESQL_SCHEMES = frozenset({"postgresql", "postgresql+psycopg"})
CRYPTOGRAPHY_KEY_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is absent or invalid."""


@dataclass(frozen=True)
class SecretValue:
    """Keep a sensitive configuration value out of ordinary representations."""

    _value: str

    def reveal(self) -> str:
        """Return the value only to the infrastructure adapter that needs it."""
        return self._value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"


@dataclass(frozen=True)
class Settings:
    """Configuration required by infrastructure adapters."""

    database_url: SecretValue


@dataclass(frozen=True)
class CryptographyKeyConfiguration:
    """Versioned external root key configuration for cryptographic adapters."""

    root_key: SecretValue
    key_version: str


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load the PostgreSQL connection from the process environment."""
    source = os.environ if environ is None else environ
    database_url = source.get(DATABASE_URL_ENVIRONMENT_VARIABLE, "").strip()

    if not database_url:
        raise ConfigurationError(
            f"{DATABASE_URL_ENVIRONMENT_VARIABLE} must be configured."
        )

    if urlsplit(database_url).scheme.lower() not in POSTGRESQL_SCHEMES:
        raise ConfigurationError(
            f"{DATABASE_URL_ENVIRONMENT_VARIABLE} must use PostgreSQL."
        )

    return Settings(database_url=SecretValue(database_url))


def load_test_database_url(environ: Mapping[str, str] | None = None) -> SecretValue:
    """Load a URL that is restricted to the dedicated PostgreSQL test database."""
    source = os.environ if environ is None else environ
    database_url = source.get(TEST_DATABASE_URL_ENVIRONMENT_VARIABLE, "").strip()

    if not database_url:
        raise ConfigurationError(
            f"{TEST_DATABASE_URL_ENVIRONMENT_VARIABLE} must be configured."
        )

    try:
        parsed_url = make_url(database_url)
    except Exception as error:
        raise ConfigurationError(
            f"{TEST_DATABASE_URL_ENVIRONMENT_VARIABLE} must be a valid PostgreSQL URL."
        ) from error

    if parsed_url.drivername != "postgresql+psycopg":
        raise ConfigurationError(
            f"{TEST_DATABASE_URL_ENVIRONMENT_VARIABLE} must use postgresql+psycopg."
        )

    if parsed_url.database != TEST_DATABASE_NAME:
        raise ConfigurationError(
            f"{TEST_DATABASE_URL_ENVIRONMENT_VARIABLE} must target {TEST_DATABASE_NAME}."
        )

    return SecretValue(database_url)


def load_private_code_master_key(
    environ: Mapping[str, str] | None = None,
) -> SecretValue:
    """Load the external 256-bit root key for private-code protection."""

    source = os.environ if environ is None else environ
    encoded_key = source.get(PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE, "").strip()
    if not encoded_key:
        raise ConfigurationError(
            f"{PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE} must be configured."
        )

    try:
        encoded_bytes = encoded_key.encode("ascii")
        decoded_key = base64.b64decode(
            encoded_bytes + b"=" * (-len(encoded_bytes) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeEncodeError, ValueError) as error:
        raise ConfigurationError(
            f"{PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE} must be a base64-encoded key."
        ) from error

    if len(decoded_key) != 32:
        raise ConfigurationError(
            f"{PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE} must encode 32 bytes."
        )
    return SecretValue(encoded_key)


def load_cryptography_key_configuration(
    environ: Mapping[str, str] | None = None,
) -> CryptographyKeyConfiguration:
    """Load the versioned root key required by cryptographic infrastructure."""

    source = os.environ if environ is None else environ
    root_key = load_private_code_master_key(source)
    key_version = source.get(CRYPTOGRAPHY_KEY_VERSION_ENVIRONMENT_VARIABLE, "").strip()

    if not CRYPTOGRAPHY_KEY_VERSION_PATTERN.fullmatch(key_version):
        raise ConfigurationError(
            f"{CRYPTOGRAPHY_KEY_VERSION_ENVIRONMENT_VARIABLE} must be configured with a valid key version."
        )

    return CryptographyKeyConfiguration(root_key=root_key, key_version=key_version)


def load_trusted_proxy_networks(
    environ: Mapping[str, str] | None = None,
) -> tuple[IPv4Network | IPv6Network, ...]:
    """Load optional proxy networks whose forwarded client IP may be trusted."""

    source = os.environ if environ is None else environ
    configured_value = source.get(TRUSTED_PROXY_CIDRS_ENVIRONMENT_VARIABLE, "")
    if not configured_value.strip():
        return ()

    networks: list[IPv4Network | IPv6Network] = []
    for raw_value in configured_value.split(","):
        value = raw_value.strip()
        if not value:
            raise ConfigurationError(
                f"{TRUSTED_PROXY_CIDRS_ENVIRONMENT_VARIABLE} contains an empty entry."
            )
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError as error:
            raise ConfigurationError(
                f"{TRUSTED_PROXY_CIDRS_ENVIRONMENT_VARIABLE} must contain valid IP networks."
            ) from error
    return tuple(networks)
