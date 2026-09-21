"""T047 tests for opaque private-code generation and keyed lookup values."""

from __future__ import annotations

import base64

from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.application.private_code import (
    PRIVATE_CODE_ENTROPY_BYTES,
    generate_private_code,
)
from backend.app.infrastructure.security.private_code_protection import (
    HMAC_DIGEST_BYTES,
    PrivateCodeProtector,
)
from backend.app.infrastructure.settings import SecretValue


def encoded_master_key(marker: int) -> SecretValue:
    return SecretValue(base64.urlsafe_b64encode(bytes([marker]) * 32).decode("ascii"))


def test_t047_private_code_uses_exactly_128_bits_and_is_opaque() -> None:
    code = generate_private_code(SequenceSecretGenerator([b"\x00" * 16]))

    assert code.entropy_bytes == PRIVATE_CODE_ENTROPY_BYTES
    assert len(base64.urlsafe_b64decode(code.value + "==")) == 16
    assert code.value == "AAAAAAAAAAAAAAAAAAAAAA"
    assert "5510000000" not in code.value
    assert "clienta@example.test" not in code.value
    assert code.value not in repr(code)


def test_t047_private_code_lookup_uses_a_keyed_digest_instead_of_the_code() -> None:
    code = generate_private_code(SequenceSecretGenerator([b"\x01" * 16]))
    protector = PrivateCodeProtector(
        master_key=encoded_master_key(2),
        secret_generator=SequenceSecretGenerator([]),
    )
    another_protector = PrivateCodeProtector(
        master_key=encoded_master_key(3),
        secret_generator=SequenceSecretGenerator([]),
    )

    digest = protector.digest(code.value)

    assert len(digest) == HMAC_DIGEST_BYTES
    assert digest != code.value.encode("ascii")
    assert digest != another_protector.digest(code.value)
