"""
Periodic background jobs (rollup, alert checks, retention purge) in the worker.

Each run holds a PostgreSQL advisory lock named after the job, so several
worker replicas never run the same job at once; a replica that finds the
lock taken simply skips that turn.
"""

# Standard library imports
import asyncio
import logging
import time
import zlib
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

# Third-party imports
from sqlalchemy import text

# Local imports
from core.storage.database import Database

logger = logging.getLogger(__name__)

#: Seconds between checks for due jobs.
TICK_SECONDS = 30.0
#: Seconds after start before the first run, so start-up finishes first.
FIRST_RUN_DELAY_SECONDS = 60.0

FailureHandler = Callable[[str, BaseException], Awaitable[None]]
SuccessHandler = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class ScheduledJob:
    """A coroutine run every ``interval_seconds``."""

    name: str
    interval_seconds: float
    run: Callable[[], Awaitable[Any]]


def lock_key(name: str) -> int:
    """Stable advisory-lock id for a job name (a signed 32-bit int fits ``pg_try_advisory_lock``)."""
    return zlib.crc32(f"chatbot-job:{name}".encode("utf-8")) - 2**31


class JobScheduler:
    """Runs jobs one at a time when they are due; a failing job is reported and retried next interval."""

    def __init__(
        self,
        database: Database,
        jobs: List[ScheduledJob],
        on_failure: Optional[FailureHandler] = None,
        on_success: Optional[SuccessHandler] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        """
        Args:
            database: Connected database (for the advisory locks).
            jobs: The jobs to run.
            on_failure: Called with the job name and error (the alert channel).
            on_success: Called after each successful run (clears a failure alert).
            clock: Monotonic time source (injectable for tests).
        """
        self._database = database
        self._jobs = jobs
        self._on_failure = on_failure
        self._on_success = on_success
        self._clock = clock
        self._next_run: Dict[str, float] = {}

    async def run_due(self) -> List[str]:
        """
        Run every job whose time has come.

        Returns:
            Names of the jobs that ran (not those skipped because another worker holds the lock).
        """
        ran: List[str] = []
        for job in self._jobs:
            now = self._clock()
            if now < self._next_run.setdefault(job.name, now + FIRST_RUN_DELAY_SECONDS):
                continue
            self._next_run[job.name] = now + job.interval_seconds
            if await self.run_now(job):
                ran.append(job.name)
        return ran

    async def run_now(self, job: ScheduledJob) -> bool:
        """Run one job under its lock; returns ``False`` when another process holds it."""
        async with self._database.engine.connect() as connection:
            key = lock_key(job.name)
            acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            if not acquired:
                logger.info("Job %s is running elsewhere; skipped", job.name)
                return False
            try:
                started = time.perf_counter()
                logger.info("Job %s started", job.name)
                result = await job.run()
                logger.info("Job %s finished in %.1fs: %s", job.name, time.perf_counter() - started, result)
                if self._on_success is not None:
                    await self._on_success(job.name)
            except Exception as exc:
                logger.exception("Job %s failed", job.name)
                if self._on_failure is not None:
                    await self._report(job.name, exc)
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                await connection.commit()
        return True

    async def _report(self, name: str, error: BaseException) -> None:
        """Hand a failure to the handler without letting a broken alert channel stop the loop."""
        try:
            await self._on_failure(name, error)
        except Exception:
            logger.exception("Could not report the failure of job %s", name)

    async def run_forever(self) -> None:
        """Check for due jobs until cancelled."""
        logger.info("Scheduler started with jobs: %s", ", ".join(job.name for job in self._jobs))
        while True:
            try:
                await self.run_due()
            except Exception:
                # e.g. the database is briefly unreachable: keep the loop alive and try again.
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)
