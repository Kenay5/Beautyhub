"""T067 unit evidence for safe public client-IP fingerprinting."""

from __future__ import annotations

from ipaddress import ip_network

from backend.app.infrastructure.security.public_request_subject import (
    PublicRequestSubjectProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue
from backend.app.web.public_request_protection import resolve_public_client_ip


KEY_RING = CryptographyKeyRing(
    CryptographyKeyConfiguration(
        root_key=SecretValue("AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="),
        key_version="v1",
    )
)


def test_t067_ip_fingerprint_is_stable_keyed_and_contains_no_plain_ip() -> None:
    protector = PublicRequestSubjectProtector(key_ring=KEY_RING)

    first = protector.fingerprint_ip("2001:db8::1")
    equivalent = protector.fingerprint_ip("2001:0db8:0:0:0:0:0:1")
    other = protector.fingerprint_ip("2001:db8::2")

    assert first == equivalent
    assert first != other
    assert b"2001:db8::1" not in first


def test_t067_untrusted_peer_cannot_spoof_forwarded_client_ip() -> None:
    resolved = resolve_public_client_ip(
        direct_host="198.51.100.20",
        forwarded_for="203.0.113.99",
        trusted_proxy_networks=(ip_network("10.0.0.0/8"),),
    )

    assert resolved == "198.51.100.20"


def test_t067_trusted_proxy_uses_nearest_untrusted_forwarded_address() -> None:
    resolved = resolve_public_client_ip(
        direct_host="10.0.0.5",
        forwarded_for="203.0.113.99, 198.51.100.20, 10.0.0.4",
        trusted_proxy_networks=(ip_network("10.0.0.0/8"),),
    )

    assert resolved == "198.51.100.20"


def test_t067_malformed_forwarded_chain_falls_back_to_trusted_peer() -> None:
    resolved = resolve_public_client_ip(
        direct_host="10.0.0.5",
        forwarded_for="not-an-ip",
        trusted_proxy_networks=(ip_network("10.0.0.0/8"),),
    )

    assert resolved == "10.0.0.5"


def test_t091_forged_forwarded_headers_do_not_change_an_untrusted_origin_fingerprint() -> None:
    protector = PublicRequestSubjectProtector(key_ring=KEY_RING)
    networks = (ip_network("10.0.0.0/8"),)

    forged_a = resolve_public_client_ip(
        direct_host="198.51.100.20",
        forwarded_for="203.0.113.99",
        trusted_proxy_networks=networks,
    )
    forged_b = resolve_public_client_ip(
        direct_host="198.51.100.20",
        forwarded_for="192.0.2.44, 10.0.0.4",
        trusted_proxy_networks=networks,
    )

    assert protector.fingerprint_ip(forged_a) == protector.fingerprint_ip(forged_b)


def test_t091_trusted_proxy_chain_produces_a_stable_origin_fingerprint() -> None:
    protector = PublicRequestSubjectProtector(key_ring=KEY_RING)
    networks = (ip_network("10.0.0.0/8"),)

    first = resolve_public_client_ip(
        direct_host="10.0.0.5",
        forwarded_for="203.0.113.99, 198.51.100.20, 10.0.0.4",
        trusted_proxy_networks=networks,
    )
    equivalent = resolve_public_client_ip(
        direct_host="10.0.0.5",
        forwarded_for="198.51.100.20, 10.0.0.4",
        trusted_proxy_networks=networks,
    )

    assert first == equivalent == "198.51.100.20"
    assert protector.fingerprint_ip(first) == protector.fingerprint_ip(equivalent)
