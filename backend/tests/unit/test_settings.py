from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.infrastructure.settings import (
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE,
    TRUSTED_PROXY_CIDRS_ENVIRONMENT_VARIABLE,
    ConfigurationError,
    load_private_code_master_key,
    load_settings,
    load_trusted_proxy_networks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FAKE_DATABASE_URL = (
    "postgresql+psycopg://beautyhub_test:placeholder@db.invalid:5432/beautyhub_test"
)


def test_load_settings_reads_a_postgresql_connection_from_external_values() -> None:
    settings = load_settings(
        {DATABASE_URL_ENVIRONMENT_VARIABLE: f"  {FAKE_DATABASE_URL}  "}
    )

    assert settings.database_url.reveal() == FAKE_DATABASE_URL


@pytest.mark.parametrize("value", [None, "", "   "])
def test_load_settings_rejects_a_missing_or_blank_connection(value: str | None) -> None:
    environment = (
        {} if value is None else {DATABASE_URL_ENVIRONMENT_VARIABLE: value}
    )

    with pytest.raises(ConfigurationError) as error:
        load_settings(environment)

    assert str(error.value) == f"{DATABASE_URL_ENVIRONMENT_VARIABLE} must be configured."


def test_load_settings_rejects_non_postgresql_connections_without_echoing_them() -> None:
    unsafe_connection = "sqlite:///private-local-data.db"

    with pytest.raises(ConfigurationError) as error:
        load_settings({DATABASE_URL_ENVIRONMENT_VARIABLE: unsafe_connection})

    assert str(error.value) == f"{DATABASE_URL_ENVIRONMENT_VARIABLE} must use PostgreSQL."
    assert unsafe_connection not in str(error.value)


def test_sensitive_configuration_values_are_redacted_from_ordinary_output() -> None:
    settings = load_settings({DATABASE_URL_ENVIRONMENT_VARIABLE: FAKE_DATABASE_URL})

    assert FAKE_DATABASE_URL not in repr(settings)
    assert str(settings.database_url) == "<redacted>"
    assert repr(settings.database_url) == "SecretValue(<redacted>)"


def test_private_code_master_key_stays_external_and_redacted() -> None:
    encoded_key = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="

    configured_key = load_private_code_master_key(
        {PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE: encoded_key}
    )

    assert configured_key.reveal() == encoded_key
    assert encoded_key not in repr(configured_key)


def test_private_code_master_key_accepts_the_base64url_value_generated_for_local_setup() -> None:
    encoded_key_without_padding = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE"

    configured_key = load_private_code_master_key(
        {PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE: encoded_key_without_padding}
    )

    assert configured_key.reveal() == encoded_key_without_padding


@pytest.mark.parametrize("encoded_key", ["", "not-base64", "AQ=="])
def test_private_code_master_key_requires_a_valid_256_bit_external_value(
    encoded_key: str,
) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_private_code_master_key(
            {PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE: encoded_key}
        )

    if encoded_key:
        assert encoded_key not in str(error.value)


def test_local_environment_files_are_ignored_but_the_example_is_allowed() -> None:
    ignored_patterns = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".env" in ignored_patterns
    assert ".env.*" in ignored_patterns
    assert "!.env.example" in ignored_patterns


def test_trusted_proxy_networks_are_optional_and_normalized() -> None:
    assert load_trusted_proxy_networks({}) == ()

    networks = load_trusted_proxy_networks(
        {TRUSTED_PROXY_CIDRS_ENVIRONMENT_VARIABLE: " 10.10.0.7/24, 2001:db8::1/64 "}
    )

    assert tuple(str(network) for network in networks) == (
        "10.10.0.0/24",
        "2001:db8::/64",
    )


@pytest.mark.parametrize("value", ["invalid", "10.0.0.1/33", "10.0.0.1,,10.0.0.2"])
def test_trusted_proxy_networks_fail_safely_when_invalid(value: str) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_trusted_proxy_networks(
            {TRUSTED_PROXY_CIDRS_ENVIRONMENT_VARIABLE: value}
        )

    assert str(error.value).startswith(TRUSTED_PROXY_CIDRS_ENVIRONMENT_VARIABLE)
