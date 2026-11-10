"""
Every backend module is named in the README.md of its folder (or the nearest parent folder that has one).

The folder READMEs are the map people and agents read before editing a package; this keeps them from
silently missing a file when one is added or renamed.
"""

import re
from pathlib import Path
from typing import List, Optional

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
#: Top-level folders whose modules must be documented; each needs a README.md of its own.
DOCUMENTED_ROOTS = ("app", "scripts")
README_NAME = "README.md"


def nearest_readme(module: Path, root: Path) -> Optional[Path]:
    """The README.md closest to ``module``, searching its folder and then parents up to ``root``."""
    for folder in [module.parent, *module.parent.parents]:
        readme = folder / README_NAME
        if readme.is_file():
            return readme
        if folder == root:
            return None
    return None


def is_named_in(module_name: str, text: str) -> bool:
    """True when ``module_name`` appears as a whole file name (``chat.py`` does not match ``admin_chat.py``)."""
    return re.search(rf"(?<![\w.-]){re.escape(module_name)}(?!\w)", text) is not None


@pytest.mark.parametrize("root_name", DOCUMENTED_ROOTS)
def test_every_module_is_named_in_its_readme(root_name: str) -> None:
    root = BACKEND_ROOT / root_name
    missing: List[str] = []
    for module in sorted(root.rglob("*.py")):
        if module.name == "__init__.py" or "__pycache__" in module.parts:
            continue
        readme = nearest_readme(module, root)
        location = module.relative_to(BACKEND_ROOT).as_posix()
        if readme is None:
            missing.append(f"{location}: no README.md in its folder or any parent up to {root_name}/")
        elif not is_named_in(module.name, readme.read_text(encoding="utf-8")):
            missing.append(f"{location}: not named in {readme.relative_to(BACKEND_ROOT).as_posix()}")
    assert not missing, "Modules missing from folder READMEs:\n" + "\n".join(missing)
