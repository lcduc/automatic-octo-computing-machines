"""
Typed readers for environment variables.

Every setting in ``config/`` is read through one of these helpers so malformed
values degrade to the documented default with a warning instead of crashing
at import time.
"""

# Standard library imports
import logging
import os
from typing import List

logger = logging.getLogger(__name__)


def env_str(name: str, default: str) -> str:
    """Read a string environment variable."""
    return os.getenv(name, default)


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back on malformed input."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %s", name, raw, default)
        return default


def env_float(name: str, default: float) -> float:
    """Read a float environment variable, falling back on malformed input."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", name, raw, default)
        return default


def env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable (``true/1/yes/on`` are truthy)."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def env_list(name: str, default: str) -> List[str]:
    """Read a comma-separated environment variable into a list."""
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]
