"""
Dependency direction between the backend packages: api -> services -> core -> models/utils.

Lower layers never import upper ones, and only ``main.py`` imports ``middleware``. This test
keeps that true as the code grows, instead of relying on reviewers to notice.
"""

import ast
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
#: Every backend package lives under this one top-level package.
APP_PACKAGE = "app"

#: Package -> top-level packages it must never import.
FORBIDDEN_IMPORTS = {
    "api": {"middleware"},
    "services": {"api", "middleware"},
    "core": {"api", "services", "middleware"},
    "models": {"api", "services", "middleware", "core"},
    "utils": {"api", "services", "middleware", "core"},
    "config": {"api", "services", "middleware", "core"},
}


def app_package(module: str) -> str:
    """The backend package a dotted module path belongs to (``app.core.x`` -> ``core``), else ``""``."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == APP_PACKAGE else ""


def imported_packages(source: Path) -> Iterator[Tuple[int, str]]:
    """Yield (line, backend package) for every absolute import in ``source``, lazy ones included."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, app_package(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, app_package(node.module)


@pytest.mark.parametrize("package", sorted(FORBIDDEN_IMPORTS))
def test_package_does_not_import_upward(package: str) -> None:
    forbidden = FORBIDDEN_IMPORTS[package]
    violations: List[str] = [
        f"{source.relative_to(BACKEND_ROOT).as_posix()}:{line} imports {target}"
        for source in sorted((BACKEND_ROOT / APP_PACKAGE / package).rglob("*.py"))
        for line, target in imported_packages(source)
        if target in forbidden
    ]
    assert not violations, "Upward imports:\n" + "\n".join(violations)
