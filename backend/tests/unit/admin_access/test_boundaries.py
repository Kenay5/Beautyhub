"""T003 scaffolding checks for the administrative layer boundaries."""

from __future__ import annotations

import importlib


ADMINISTRATIVE_PACKAGES = (
    "backend.app.domain.authentication",
    "backend.app.domain.authorization",
    "backend.app.domain.sessions",
    "backend.app.domain.audit",
    "backend.app.application.admin_access",
    "backend.app.infrastructure.notifications",
    "backend.app.web.admin_auth",
    "backend.app.cli",
)


def test_t003_administrative_boundary_packages_are_importable() -> None:
    loaded = tuple(importlib.import_module(name).__name__ for name in ADMINISTRATIVE_PACKAGES)

    assert loaded == ADMINISTRATIVE_PACKAGES
