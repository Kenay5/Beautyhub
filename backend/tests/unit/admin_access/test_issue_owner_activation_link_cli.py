"""T032 unit evidence for the protected owner-link command boundary."""

from __future__ import annotations

import pytest

from backend.app.cli.issue_owner_activation_link import parse_command_arguments


def test_t032_owner_activation_link_command_accepts_no_shell_secrets() -> None:
    parse_command_arguments(())

    with pytest.raises(SystemExit):
        parse_command_arguments(("synthetic.owner@example.test",))
