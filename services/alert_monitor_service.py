"""
Operator alert rules (OBS-04, ADM-09), checked every few minutes by the worker.

Condition rules (service down, error spike, disk, overdue tickets, spend)
alert when they start, repeat after a cool-down while they last and send one
"resolved" message when they clear. Event rules (failed uploads, failed jobs)
alert once per event. State lives in ``alert_states`` so a restart neither
repeats nor loses an alert.
"""

# Standard library imports
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

# Third-party imports
import httpx

# Local imports
from core.infrastructure.alert_notifier import AlertDeliveryError, AlertNotifier
from core.storage.database import Database
from core.storage.monitoring_repository import MonitoringRepository
from models.usage_policy import MICRO_USD_PER_USD
from .settings_service import SettingsService
from .usage_service import UsageService

logger = logging.getLogger(__name__)

#: A lasting problem is re-sent after this long.
ALERT_COOLDOWN = timedelta(hours=6)
#: Window and thresholds of the error-spike rule.
ERROR_WINDOW = timedelta(minutes=15)
ERROR_RATIO_THRESHOLD = 0.2
MIN_ERRORS_FOR_SPIKE = 5
#: Share of the data disk in use that triggers the disk alert.
DISK_USAGE_THRESHOLD = 0.8
#: Seconds allowed for the API readiness probe.
READY_PROBE_TIMEOUT_SECONDS = 10.0
#: Failed uploads named in one alert.
MAX_FAILURES_LISTED = 5

RULE_SERVICE_DOWN = "service_down"
RULE_ERROR_SPIKE = "error_spike"
RULE_DISK = "disk_usage"
RULE_OVERDUE_TICKETS = "overdue_tickets"
RULE_SPEND = "spend"
RULE_INGESTION_FAILED = "ingestion_failed"
#: Prefix of the per-job failure rules (``job_failed:<name>``).
RULE_JOB_FAILED = "job_failed"

SPEND_LEVEL_ANONYMOUS = "anonymous_paused"
SPEND_LEVEL_CAP = "cap_reached"
#: Spend levels, lowest first; each is reported once a month.
SPEND_LEVELS = (SPEND_LEVEL_ANONYMOUS, SPEND_LEVEL_CAP)

HttpClientFactory = Callable[[], httpx.AsyncClient]


@dataclass(frozen=True)
class Problem:
    """A condition rule's finding: a short subject and the details."""

    subject: str
    body: str


class AlertMonitorService:
    """Evaluates the alert rules and sends what changed."""

    def __init__(
        self,
        database: Database,
        notifier: AlertNotifier,
        settings: SettingsService,
        usage: UsageService,
        disk_path: str,
        api_ready_url: str = "",
        http_client_factory: Optional[HttpClientFactory] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        """
        Args:
            database: Connected database.
            notifier: The operator alert channel.
            settings: Runtime policy (spend cap); reloaded before each check.
            usage: This month's spend.
            disk_path: A path on the data disk (uploads, database volume).
            api_ready_url: The API's ``/health/ready``; empty skips the service-down rule.
            http_client_factory: Builds the probe's HTTP client (tests pass a mock transport).
            clock: Current UTC time (injectable for tests).
        """
        self._database = database
        self._notifier = notifier
        self._settings = settings
        self._usage = usage
        self._disk_path = disk_path
        self._api_ready_url = api_ready_url
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=READY_PROBE_TIMEOUT_SECONDS)
        )
        self._clock = clock

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def check(self) -> List[str]:
        """
        Evaluate every rule once.

        Returns:
            The rules that sent an alert (or a resolved notice) this time.
        """
        await self._settings.load()
        sent: List[str] = []
        conditions = (
            (RULE_SERVICE_DOWN, self._service_down),
            (RULE_ERROR_SPIKE, self._error_spike),
            (RULE_DISK, self._disk_usage),
            (RULE_OVERDUE_TICKETS, self._overdue_tickets),
        )
        for rule, evaluate in conditions:
            try:
                if await self._apply(rule, await evaluate()):
                    sent.append(rule)
            except Exception:
                # One broken rule must not silence the others.
                logger.exception("Alert rule %s failed", rule)
        for rule, evaluate in ((RULE_SPEND, self._spend), (RULE_INGESTION_FAILED, self._ingestion_failures)):
            try:
                if await evaluate():
                    sent.append(rule)
            except Exception:
                logger.exception("Alert rule %s failed", rule)
        return sent

    async def job_failed(self, job: str, error: BaseException) -> None:
        """Report a failed scheduled job (rollup, purge…); repeats are held back by the cool-down."""
        problem = Problem(f"Scheduled job '{job}' failed", f"{type(error).__name__}: {str(error)[:300]}")
        await self._apply(f"{RULE_JOB_FAILED}:{job}", problem)

    async def job_succeeded(self, job: str) -> None:
        """Clear a job's failure state (sends "resolved" if it had failed)."""
        await self._apply(f"{RULE_JOB_FAILED}:{job}", None)

    # ------------------------------------------------------------------
    # State handling
    # ------------------------------------------------------------------

    async def _send(self, subject: str, body: str) -> bool:
        """Deliver one alert; a delivery failure is logged, never raised."""
        try:
            await self._notifier.send(subject, body)
            return True
        except AlertDeliveryError:
            logger.exception("Alert %r could not be delivered", subject)
            return False

    async def _apply(self, rule: str, problem: Optional[Problem]) -> bool:
        """Send a condition rule's alert or resolution when due; returns whether a message was sent."""
        now = self._clock()
        async with self._database.session() as session:
            state = await MonitoringRepository(session).state(rule)
            if problem is None:
                if not state.firing:
                    return False
                state.firing = False
                logger.info("Alert %s resolved", rule)
                return await self._send(f"Resolved: {rule.replace('_', ' ')}", "The condition has cleared.")
            if state.firing and state.last_sent_at is not None and now - state.last_sent_at < ALERT_COOLDOWN:
                return False
            logger.warning("Alert %s: %s", rule, problem.subject)
            delivered = await self._send(problem.subject, problem.body)
            if delivered:
                state.firing = True
                state.last_sent_at = now
            return delivered

    # ------------------------------------------------------------------
    # Condition rules
    # ------------------------------------------------------------------

    async def _service_down(self) -> Optional[Problem]:
        """The API's readiness check fails or does not answer."""
        if not self._api_ready_url:
            return None
        try:
            async with self._http_client_factory() as client:
                response = await client.get(self._api_ready_url)
        except httpx.HTTPError as exc:
            logger.exception("API readiness probe failed")
            return Problem("Chat API is down", f"The readiness check did not answer ({type(exc).__name__}).")
        if response.status_code == 200:
            return None
        try:
            checks = response.json().get("checks", {})
        except ValueError:
            logger.exception("API readiness answered without JSON")
            checks = {}
        failing = ", ".join(name for name, healthy in checks.items() if not healthy) or f"HTTP {response.status_code}"
        return Problem("Chat API is not ready", f"Failing checks: {failing}.")

    async def _error_spike(self) -> Optional[Problem]:
        """Too many failed answers in the last minutes."""
        async with self._database.session() as session:
            turns, errors = await MonitoringRepository(session).turn_errors_since(self._clock() - ERROR_WINDOW)
        if errors < MIN_ERRORS_FOR_SPIKE or errors < turns * ERROR_RATIO_THRESHOLD:
            return None
        minutes = int(ERROR_WINDOW.total_seconds() // 60)
        return Problem("Chat error spike", f"{errors} of {turns} answers failed in the last {minutes} minutes.")

    async def _disk_usage(self) -> Optional[Problem]:
        """The data disk is nearly full."""
        usage = shutil.disk_usage(self._disk_path)
        ratio = usage.used / usage.total if usage.total else 0.0
        if ratio < DISK_USAGE_THRESHOLD:
            return None
        free_gb = usage.free / 1024**3
        return Problem("Disk almost full", f"The data disk is {ratio:.0%} full ({free_gb:.1f} GB free).")

    async def _overdue_tickets(self) -> Optional[Problem]:
        """Support tickets waiting past their promised reply time."""
        async with self._database.session() as session:
            count, oldest = await MonitoringRepository(session).overdue_tickets(self._clock())
        if count == 0:
            return None
        hours = (self._clock() - oldest).total_seconds() / 3600 if oldest else 0.0
        return Problem(f"{count} support ticket(s) overdue", f"The oldest is {hours:.1f} h past its due time.")

    # ------------------------------------------------------------------
    # Event rules
    # ------------------------------------------------------------------

    async def _spend(self) -> bool:
        """Alert once per month for each spend level reached (anonymous pause, cap)."""
        policy = self._settings.usage_policy()
        if policy.spend_cap_usd <= 0:
            return False
        spent = (await self._usage.month_spend())["cost_micro_usd"]
        if spent >= policy.spend_limit_micro_usd(logged_in=True):
            level = SPEND_LEVEL_CAP
        elif spent >= policy.spend_limit_micro_usd(logged_in=False):
            level = SPEND_LEVEL_ANONYMOUS
        else:
            return False
        month = f"{self._clock():%Y-%m}"
        async with self._database.session() as session:
            state = await MonitoringRepository(session).state(RULE_SPEND)
            reported_month, _, reported_level = (state.cursor or "").partition(":")
            if reported_month == month and SPEND_LEVELS.index(reported_level) >= SPEND_LEVELS.index(level):
                return False
            spent_usd = spent / MICRO_USD_PER_USD
            subject = "Monthly spend cap reached" if level == SPEND_LEVEL_CAP else "Spend threshold reached"
            detail = (
                "Chat is paused for everyone until next month or a higher cap."
                if level == SPEND_LEVEL_CAP
                else "Anonymous visitors are paused; signed-in users can still chat."
            )
            delivered = await self._send(subject, f"${spent_usd:.2f} of the ${policy.spend_cap_usd:.2f} cap spent. {detail}")
            if delivered:
                state.cursor = f"{month}:{level}"
                state.last_sent_at = self._clock()
            return delivered

    async def _ingestion_failures(self) -> bool:
        """Alert about uploads that failed since the last alert."""
        async with self._database.session() as session:
            repository = MonitoringRepository(session)
            state = await repository.state(RULE_INGESTION_FAILED)
            since = datetime.fromisoformat(state.cursor) if state.cursor else None
            failures = await repository.failed_uploads_since(since)
            if since is None:
                # First run: remember where we are instead of reporting historic failures.
                state.cursor = (failures[-1].processed_at if failures else self._clock()).isoformat()
                return False
            if not failures:
                return False
            names = ", ".join(doc.original_filename or doc.title for doc in failures[:MAX_FAILURES_LISTED])
            more = f" and {len(failures) - MAX_FAILURES_LISTED} more" if len(failures) > MAX_FAILURES_LISTED else ""
            delivered = await self._send(f"{len(failures)} upload(s) failed to ingest", f"{names}{more}. See Knowledge in the admin web.")
            if delivered:
                state.cursor = failures[-1].processed_at.isoformat()
                state.last_sent_at = self._clock()
            return delivered
