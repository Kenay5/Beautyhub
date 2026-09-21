"""T026 unit evidence for recovery-code generation and validation."""

from __future__ import annotations

import base64

import pytest

from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import (
    RECOVERY_CODE_ALPHABET,
    RecoveryCodeError,
    RecoveryCodeService,
    normalize_recovery_code,
)
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


def _service(tokens: tuple[bytes, ...]) -> RecoveryCodeService:
    key_ring = CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x61" * 32).decode("ascii")),
            key_version="v1",
        )
    )
    return RecoveryCodeService(
        secret_generator=SequenceSecretGenerator(tokens),
        protector=RecoveryCodeProtector(key_ring=key_ring),
    )


def test_t026_generates_exactly_ten_unique_formatted_codes_and_only_digests() -> None:
    batch = _service(tuple(bytes([index]) * 16 for index in range(10))).generate()

    assert len(batch) == 10
    assert len({code.display_value for code in batch}) == 10
    assert batch[0].display_value == "AAAA-AAAA-AAAA-AAAA"
    assert all(
        len(code.display_value) == 19
        and code.display_value.count("-") == 3
        and len(code.lookup_digest) == 32
        and code.display_value.encode("ascii") not in code.lookup_digest
        for code in batch
    )


@pytest.mark.parametrize(
    "value",
    (
        "ABCD-EFGH-JKLM-NPQR",
        " abcd-efgh-jklm-npqr ",
        "abcdEFGHjklmNPQR",
        "ABCD--EFGH--JKLM--NPQR",
    ),
)
def test_t026_normalizes_only_outer_spaces_hyphens_and_case(value: str) -> None:
    assert normalize_recovery_code(value) == "ABCDEFGHJKLMNPQR"


@pytest.mark.parametrize(
    "value",
    (
        "ABCD EFGH-JKLM-NPQR",
        "ABCD-EFGH-IJKL-NPQR",
        "ABCD-EFGH-JKLM-0PQR",
        "ABCD-EFGH-JKLM-NPQR!",
        "ABCD-EFGH-JKLM-NPQ",
    ),
)
def test_t026_rejects_internal_spaces_forbidden_symbols_and_wrong_lengths(value: str) -> None:
    assert normalize_recovery_code(value) is None


def test_t026_matches_a_valid_code_without_consuming_it_or_other_codes() -> None:
    service = _service(tuple(bytes([index]) * 16 for index in range(10)))
    batch = service.generate()
    active_digests = {code.lookup_digest for code in batch}

    matched = service.match(
        value=" aaaa-aaaa-aaaa-aaaa ", active_lookup_digests=active_digests
    )

    assert matched == batch[0].lookup_digest
    assert active_digests == {code.lookup_digest for code in batch}


def test_t026_rejects_an_incorrect_code_without_changing_active_codes() -> None:
    service = _service(tuple(bytes([index]) * 16 for index in range(10)))
    active_digests = {code.lookup_digest for code in service.generate()}
    original_digests = active_digests.copy()

    assert service.match(
        value="ZZZZ-ZZZZ-ZZZZ-ZZZZ", active_lookup_digests=active_digests
    ) is None
    assert active_digests == original_digests


def test_t026_fails_safely_when_entropy_cannot_make_a_unique_batch() -> None:
    service = _service((b"\x00" * 16,) * 101)

    with pytest.raises(RecoveryCodeError):
        service.generate()

    assert set(RECOVERY_CODE_ALPHABET) == set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
