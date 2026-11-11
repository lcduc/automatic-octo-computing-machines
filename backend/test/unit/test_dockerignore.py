"""
The API image must never contain what a local run wrote (PRIV-01) or the test suite (OPT-09).

A local ``docker build backend`` uses the working tree as its context, so ``backend/.dockerignore``
is the only thing standing between local logs and uploads and a pushed image.
"""

from pathlib import Path
from typing import Set

DOCKERIGNORE = Path(__file__).resolve().parents[2] / ".dockerignore"

#: Context entries that must stay out of the image.
MUST_EXCLUDE = {"data/", "test/", ".env", "SSL/", "model_weights/"}
#: Context entries the Dockerfile needs; an ignore line naming one breaks the image.
MUST_INCLUDE = {"app/", "scripts/", "migrations/", "alembic.ini", "start.sh", "requirements.txt"}


def ignore_entries() -> Set[str]:
    """Non-comment, non-blank lines of ``backend/.dockerignore``."""
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")}


def test_runtime_data_and_tests_are_excluded() -> None:
    missing = MUST_EXCLUDE - ignore_entries()
    assert not missing, f"backend/.dockerignore must exclude: {sorted(missing)}"


def test_files_the_image_needs_are_not_excluded() -> None:
    entries = ignore_entries()
    blocked = {path for path in MUST_INCLUDE if path in entries or path.rstrip("/") in entries}
    assert not blocked, f"backend/.dockerignore excludes files the image needs: {sorted(blocked)}"
