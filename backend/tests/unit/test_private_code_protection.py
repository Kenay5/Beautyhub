"""T048 tests for authenticated private-code encryption."""

from __future__ import annotations

import base64

import pytest

from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.application.private_code import generate_private_code
from backend.app.infrastructure.security.private_code_protection import (
    PrivateCodeDecryptionError,
    PrivateCodeProtector,
)
from backend.app.infrastructure.settings import SecretValue


def master_key(marker: int) -> SecretValue:
    return SecretValue(base64.urlsafe_b64encode(bytes([marker]) * 32).decode("ascii"))


def test_t048_encrypts_and_recovers_a_private_code_with_the_external_key() -> None:
    code = generate_private_code(SequenceSecretGenerator([b"\x04" * 16]))
    protector = PrivateCodeProtector(
        master_key=master_key(5),
        secret_generator=SequenceSecretGenerator([b"\x06" * 12]),
    )

    ciphertext = protector.encrypt(code)

    assert code.value.encode("ascii") not in ciphertext
    assert protector.decrypt(ciphertext) == code


def test_t048_rejects_a_tampered_ciphertext_without_revealing_the_code() -> None:
    code = generate_private_code(SequenceSecretGenerator([b"\x07" * 16]))
    protector = PrivateCodeProtector(
        master_key=master_key(8),
        secret_generator=SequenceSecretGenerator([b"\x09" * 12]),
    )
    ciphertext = bytearray(protector.encrypt(code))
    ciphertext[-1] ^= 1

    with pytest.raises(PrivateCodeDecryptionError) as error:
        protector.decrypt(bytes(ciphertext))

    assert code.value not in str(error.value)


def test_t048_rejects_decryption_with_a_different_external_key() -> None:
    code = generate_private_code(SequenceSecretGenerator([b"\x0a" * 16]))
    encryptor = PrivateCodeProtector(
        master_key=master_key(11),
        secret_generator=SequenceSecretGenerator([b"\x0c" * 12]),
    )
    decryptor = PrivateCodeProtector(
        master_key=master_key(13),
        secret_generator=SequenceSecretGenerator([]),
    )

    with pytest.raises(PrivateCodeDecryptionError):
        decryptor.decrypt(encryptor.encrypt(code))
