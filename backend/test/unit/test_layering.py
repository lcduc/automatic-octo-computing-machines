"""
Dependency direction between the backend packages: api -> services -> core -> models/utils.

Lower layers never import upper ones, only ``main.py`` imports ``middleware``, and only the HTTP
layer (``api``, ``middleware``) imports the web framework. This test keeps that true as the code
grows, instead of relying on reviewers to notice.
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
#: Web-framework packages; below the HTTP layer the code must stay framework-free.
WEB_FRAMEWORKS = {"fastapi", "starlette"}
#: Packages allowed to import a web framework.
HTTP_PACKAGES = {"api", "middleware"}


def app_package(module: str) -> str:
    """The backend package a dotted module path belongs to (``app.core.x`` -> ``core``), else ``""``."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == APP_PACKAGE else ""


def absolute_module(source: Path, node: ast.ImportFrom) -> str:
    """The dotted module an ``from ... import`` names, resolving relative imports against ``source``."""
    if node.level == 0:
        return node.module or ""
    package = list(source.relative_to(BACKEND_ROOT).with_suffix("").parts[:-1])
    base = package[: len(package) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def imported_modules(source: Path) -> Iterator[Tuple[int, str]]:
    """Yield (line, dotted module) for every import in ``source``, lazy and relative ones included."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.lineno, absolute_module(source, node)


def package_sources(package: str) -> List[Path]:
    """Every Python file of one backend package."""
    return sorted((BACKEND_ROOT / APP_PACKAGE / package).rglob("*.py"))


@pytest.mark.parametrize("package", sorted(FORBIDDEN_IMPORTS))
def test_package_does_not_import_upward(package: str) -> None:
    forbidden = FORBIDDEN_IMPORTS[package]
    violations: List[str] = [
        f"{source.relative_to(BACKEND_ROOT).as_posix()}:{line} imports {app_package(module)}"
        for source in package_sources(package)
        for line, module in imported_modules(source)
        if app_package(module) in forbidden
    ]
    assert not violations, "Upward imports:\n" + "\n".join(violations)


@pytest.mark.parametrize("package", sorted(set(FORBIDDEN_IMPORTS) - HTTP_PACKAGES))
def test_package_does_not_import_web_framework(package: str) -> None:
    violations: List[str] = [
        f"{source.relative_to(BACKEND_ROOT).as_posix()}:{line} imports {module}"
        for source in package_sources(package)
        for line, module in imported_modules(source)
        if module.split(".")[0] in WEB_FRAMEWORKS
    ]
    assert not violations, "Web framework imported below the HTTP layer:\n" + "\n".join(violations)


def test_relative_imports_resolve_inside_app() -> None:
    """A relative import is resolved against its file, so it is checked like an absolute one."""
    source = BACKEND_ROOT / APP_PACKAGE / "core" / "agent" / "chatbot.py"
    node = ast.parse("from ..retrieval import x").body[0]
    assert absolute_module(source, node) == "app.core.retrieval"
