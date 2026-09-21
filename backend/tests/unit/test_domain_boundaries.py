from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOMAIN_ROOT = PROJECT_ROOT / "backend" / "app" / "domain"

FORBIDDEN_IMPORT_PREFIXES = (
    "alembic",
    "asyncpg",
    "backend.app.application",
    "backend.app.infrastructure",
    "backend.app.web",
    "fastapi",
    "httpx",
    "psycopg",
    "pydantic",
    "requests",
    "resend",
    "sqlalchemy",
    "starlette",
)


def _module_name(source_path: Path) -> str:
    relative_path = source_path.relative_to(PROJECT_ROOT).with_suffix("")
    module_parts = list(relative_path.parts)
    if module_parts[-1] == "__init__":
        module_parts.pop()
    return ".".join(module_parts)


def _imported_modules(source_path: Path) -> set[str]:
    syntax_tree = ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
    )
    current_module = _module_name(source_path)
    current_package = (
        current_module
        if source_path.name == "__init__.py"
        else current_module.rpartition(".")[0]
    )
    imported_modules: set[str] = set()

    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if node.level:
                relative_name = f"{'.' * node.level}{module_name}"
                imported_modules.add(
                    importlib.util.resolve_name(relative_name, current_package)
                )
            elif module_name:
                imported_modules.add(module_name)

    return imported_modules


def _is_forbidden(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )


def test_domain_package_is_importable() -> None:
    domain_package = importlib.import_module("backend.app.domain")

    assert domain_package.__name__ == "backend.app.domain"


def test_domain_does_not_import_frameworks_or_adapters() -> None:
    violations = {
        str(source_path.relative_to(PROJECT_ROOT)): sorted(
            module_name
            for module_name in _imported_modules(source_path)
            if _is_forbidden(module_name)
        )
        for source_path in DOMAIN_ROOT.rglob("*.py")
    }
    violations = {
        source_path: modules
        for source_path, modules in violations.items()
        if modules
    }

    assert violations == {}, f"Domain dependency violations: {violations}"
