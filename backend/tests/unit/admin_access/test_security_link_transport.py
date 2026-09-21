"""T028 unit evidence for opaque security-link transport."""

import pytest
from pydantic import ValidationError

from backend.app.web.admin_auth.security_link_transport import (
    SecurityLinkTokenBody,
    decode_security_link_token,
    encode_security_link_token,
    security_link_fragment,
)


def test_t028_encodes_exactly_256_bits_without_personal_data() -> None:
    token = bytes(range(32))

    encoded = encode_security_link_token(token)

    assert encoded == "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    assert len(encoded) == 43
    assert "=" not in encoded
    assert decode_security_link_token(encoded) == token
    assert security_link_fragment(token) == f"#token={encoded}"


@pytest.mark.parametrize(
    "value",
    [
        "short",
        "A" * 42,
        "A" * 44,
        "A" * 42 + "=",
        "A" * 42 + "+",
        "_" * 43,
    ],
)
def test_t028_rejects_noncanonical_or_non_256_bit_tokens(value: str) -> None:
    with pytest.raises(ValueError, match="security link token is invalid"):
        decode_security_link_token(value)
    with pytest.raises(ValidationError):
        SecurityLinkTokenBody(token=value)


def test_t028_body_contract_exposes_only_the_decoded_opaque_token() -> None:
    raw_token = b"\xa5" * 32
    body = SecurityLinkTokenBody(token=encode_security_link_token(raw_token))

    assert body.model_dump() == {"token": encode_security_link_token(raw_token)}
    assert body.decoded_token() == raw_token
