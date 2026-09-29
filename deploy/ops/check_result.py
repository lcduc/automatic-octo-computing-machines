"""
Outcome of one preflight or security check, and how a list of them is reported.
"""

# Standard library imports
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class CheckResult:
    """One check: passed or not, why, and whether a failure blocks the deployment."""

    name: str
    ok: bool
    detail: str
    #: A failed fatal check stops the install/deploy; a non-fatal one is a warning.
    fatal: bool = True


def report(results: Sequence[CheckResult], out: Callable[[str], None] = print) -> bool:
    """
    Print one line per check.

    Returns:
        True when no fatal check failed.
    """
    for result in results:
        mark = "ok  " if result.ok else ("FAIL" if result.fatal else "warn")
        out(f"  [{mark}] {result.name}: {result.detail}")
    return all(result.ok or not result.fatal for result in results)
