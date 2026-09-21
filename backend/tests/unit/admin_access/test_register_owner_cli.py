"""T031 unit evidence for the interactive owner-registration command boundary."""

from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
from types import SimpleNamespace

import pytest

from backend.app.cli import register_owner


def test_t031_owner_registration_command_accepts_no_email_shell_argument() -> None:
    register_owner.parse_command_arguments(())

    with pytest.raises(SystemExit):
        register_owner.parse_command_arguments(("synthetic.owner@example.test",))


def test_t031_owner_registration_command_prompts_for_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    registered_emails: list[str] = []

    class FakeEngine:
        @contextmanager
        def begin(self):
            yield object()

        def dispose(self) -> None:
            return None

    class FakeRegistration:
        def __init__(self, **_: object) -> None:
            return None

        def register(self, *, email: str) -> None:
            registered_emails.append(email)

    monkeypatch.setattr(
        register_owner,
        "load_settings",
        lambda: SimpleNamespace(database_url=object()),
    )
    monkeypatch.setattr(register_owner, "load_cryptography_key_configuration", lambda: object())
    monkeypatch.setattr(register_owner, "create_postgres_engine", lambda _: FakeEngine())
    monkeypatch.setattr(register_owner, "PostgresOwnerBootstrapRegistrationStore", lambda _: object())
    monkeypatch.setattr(register_owner, "AdministrativeEmailProtector", lambda **_: object())
    monkeypatch.setattr(register_owner, "CryptographyKeyRing", lambda _: object())
    monkeypatch.setattr(register_owner, "RegisterOwnerBootstrap", FakeRegistration)

    output = StringIO()
    result = register_owner.main(
        (),
        input_function=lambda prompt: prompts.append(prompt) or "synthetic.owner@example.test",
        output=output,
        error_output=StringIO(),
    )

    assert result == 0
    assert prompts == ["Owner email: "]
    assert registered_emails == ["synthetic.owner@example.test"]
    assert output.getvalue() == "Owner registration completed.\n"
