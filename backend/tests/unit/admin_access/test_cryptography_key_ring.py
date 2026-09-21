"""T005 evidence for external, versioned, purpose-separated key derivation."""

from __future__ import annotations

import base64

import pytest

from backend.app.infrastructure.security.cryptography_key_ring import (
    CryptographyKeyConfigurationError,
    CryptographyKeyRing,
)
from backend.app.infrastructure.settings import (
    CRYPTOGRAPHY_KEY_VERSION_ENVIRONMENT_VARIABLE,
    PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE,
    ConfigurationError,
    load_cryptography_key_configuration,
)


def _environment(*, key_version: str = "v1") -> dict[str, str]:
    return {
        PRIVATE_CODE_MASTER_KEY_ENVIRONMENT_VARIABLE: base64.urlsafe_b64encode(
            b"\x01" * 32
        ).decode("ascii"),
        CRYPTOGRAPHY_KEY_VERSION_ENVIRONMENT_VARIABLE: key_version,
    }


def test_t005_loads_only_an_external_versioned_root_key() -> None:
    configuration = load_cryptography_key_configuration(_environment())

    assert configuration.key_version == "v1"
    assert configuration.root_key.reveal() != ""
    assert "AQ" not in repr(configuration)


@pytest.mark.parametrize("key_version", ("", " ", "v 1", "v/1", "-v1"))
def test_t005_rejects_missing_or_invalid_key_versions(key_version: str) -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_cryptography_key_configuration(_environment(key_version=key_version))

    assert CRYPTOGRAPHY_KEY_VERSION_ENVIRONMENT_VARIABLE in str(raised.value)


def test_t005_derives_distinct_stable_keys_per_approved_purpose() -> None:
    configuration = load_cryptography_key_configuration(_environment())
    first_ring = CryptographyKeyRing(configuration)
    second_ring = CryptographyKeyRing(configuration)

    totp_key = first_ring.derive("totp-encryption")
    link_key = first_ring.derive("security-link-lookup")

    assert len(totp_key) == 32
    assert totp_key != link_key
    assert second_ring.derive("totp-encryption") == totp_key


def test_t005_rejects_unapproved_derivation_purposes() -> None:
    ring = CryptographyKeyRing(load_cryptography_key_configuration(_environment()))

    with pytest.raises(CryptographyKeyConfigurationError):
        ring.derive("arbitrary-purpose")
