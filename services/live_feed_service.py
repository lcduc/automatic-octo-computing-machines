"""
The admin dashboards' live feed (answered turns, new handoffs) over PostgreSQL LISTEN/NOTIFY.

Any process publishes with ``pg_notify``; every API process listens on one
dedicated connection and fans events out to its connected dashboards, so the
feed works across processes without a message broker.
"""

# Standard library imports
import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

# Third-party imports
import asyncpg
from sqlalchemy import text
from sqlalchemy.engine import make_url

# Local imports
from core.storage.database import Database

logger = logging.getLogger(__name__)

LIVE_CHANNEL = "chatbot_live"
#: Events buffered per dashboard before new ones are dropped.
LIVE_QUEUE_SIZE = 200
#: NOTIFY payloads must stay under 8000 bytes.
MAX_PAYLOAD_BYTES = 7000
RECONNECT_SECONDS = 5
#: How often an idle listening connection is checked, and how long the check may take.
KEEPALIVE_SECONDS = 30
KEEPALIVE_TIMEOUT_SECONDS = 10


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """The plain ``postgresql://`` DSN asyncpg expects, from a SQLAlchemy URL."""
    return make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)


class LiveFeedService:
    """Publishes events to every process and delivers them to this process's subscribers."""

    def __init__(self, database: Database, dsn: str):
        """
        Args:
            database: Connected database (used to publish).
            dsn: Plain PostgreSQL DSN for the listening connection.
        """
        self._database = database
        self._dsn = dsn
        self._subscribers: Set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self._listening = asyncio.Event()

    def subscribe(self) -> asyncio.Queue:
        """Register a dashboard; pair with :meth:`unsubscribe`."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=LIVE_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a dashboard."""
        self._subscribers.discard(queue)

    async def publish(self, event: Dict[str, Any]) -> None:
        """Send ``event`` to the dashboards of every API process (best effort)."""
        payload = json.dumps(event, default=str)
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            logger.warning("Live event %s too large to publish", event.get("type"))
            return
        try:
            async with self._database.session() as session:
                await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": LIVE_CHANNEL, "payload": payload})
        except Exception:
            # The feed is informational; a failure must never fail the chat turn that produced it.
            logger.exception("Could not publish a live event")

    async def start(self) -> None:
        """Start listening in the background (reconnects on its own)."""
        self._task = asyncio.create_task(self._listen())

    async def wait_listening(self, timeout: float) -> bool:
        """Wait until the listener is connected (for tests and start-up checks)."""
        try:
            await asyncio.wait_for(self._listening.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self) -> None:
        """Stop listening."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _listen(self) -> None:
        """Keep one LISTEN connection open, reconnecting after failures."""
        while True:
            connection = None
            try:
                connection = await asyncpg.connect(self._dsn)
                closed = asyncio.Event()
                connection.add_termination_listener(lambda _connection: closed.set())
                await connection.add_listener(LIVE_CHANNEL, self._on_notify)
                self._listening.set()
                logger.info("Live feed listening on %s", LIVE_CHANNEL)
                while not closed.is_set():
                    try:
                        await asyncio.wait_for(closed.wait(), timeout=KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        # A silently dropped connection never fires the termination callback.
                        await connection.fetchval("SELECT 1", timeout=KEEPALIVE_TIMEOUT_SECONDS)
                logger.warning("Live feed connection closed; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Live feed listener failed; retrying in %ss", RECONNECT_SECONDS)
            finally:
                self._listening.clear()
                if connection is not None and not connection.is_closed():
                    await connection.close()
            await asyncio.sleep(RECONNECT_SECONDS)

    def _on_notify(self, _connection, _pid: int, _channel: str, payload: str) -> None:
        """Fan one notification out to local subscribers, dropping it for those that fell behind."""
        try:
            event = json.loads(payload)
        except ValueError:
            logger.exception("Malformed live event")
            return
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("Live dashboard is behind; dropping an event")
