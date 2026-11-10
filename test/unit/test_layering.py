"""
Dependency direction between the backend packages: api -> services -> core -> models/utils.

Lower layers never import upper ones, and only ``main.py`` imports ``middleware``. This test
keeps that true as the code grows, instead of relying on reviewers to notice.
"""

import ast
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Package -> top-level packages it must never import.
FORBIDDEN_IMPORTS = {
    "api": {"middleware"},
    "services": {"api", "middleware"},
    "core": {"api", "services", "middleware"},
    "models": {"api", "services", "middleware", "core"},
    "utils": {"api", "services", "middleware", "core"},
    "config": {"api", "services", "middleware", "core"},
}


def imported_packages(source: Path) -> Iterator[Tuple[int, str]]:
    """Yield (line, top-level package) for every absolute import in ``source``, lazy ones included."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module.split(".")[0]


@pytest.mark.parametrize("package", sorted(FORBIDDEN_IMPORTS))
def test_package_does_not_import_upward(package: str) -> None:
    forbidden = FORBIDDEN_IMPORTS[package]
    violations: List[str] = [
        f"{source.relative_to(REPO_ROOT).as_posix()}:{line} imports {target}"
        for source in sorted((REPO_ROOT / package).rglob("*.py"))
        for line, target in imported_packages(source)
        if target in forbidden
    ]
    assert not violations, "Upward imports:\n" + "\n".join(violations)
