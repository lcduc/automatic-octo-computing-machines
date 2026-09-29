"""
Readiness of the chat path (ARC-07): database, pipeline, model-server and LLM provider.

The LLM probe is a free metadata call, cached so a frequent healthcheck never
turns into a stream of provider requests.
"""

# Standard library imports
import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Seconds an LLM reachability result is reused.
LLM_CHECK_CACHE_SECONDS = 300


class ReadinessService:
    """Runs the readiness checks for ``/health/ready``."""

    def __init__(self, database, model_server=None, clock=time.monotonic):
        """
        Args:
            database: Connected database.
            model_server: Model-server client, or ``None`` when models run in-process.
            clock: Monotonic time source (injectable for tests).
        """
        self._database = database
        self._model_server = model_server
        self._clock = clock
        self._llm_result: Optional[bool] = None
        self._llm_checked_at = 0.0

    async def checks(self, pipeline_built: bool, llm) -> Dict[str, Any]:
        """Each check's result (``True`` = healthy)."""
        checks: Dict[str, Any] = {"database": await self._database.ping(), "chat_pipeline": pipeline_built}
        if self._model_server is not None:
            checks["model_server"] = await self._model_server_ready()
        if llm is not None:
            checks["llm"] = await self._llm_reachable(llm)
        return checks

    async def _model_server_ready(self) -> bool:
        """The model-server answers and has its models loaded."""
        try:
            status = await asyncio.to_thread(self._model_server.ready)
        except Exception:
            logger.exception("Model-server readiness check failed")
            return False
        return status.get("status") == "ok"

    async def _llm_reachable(self, llm) -> bool:
        """The provider's API is reachable (cached)."""
        if self._llm_result is not None and self._clock() - self._llm_checked_at < LLM_CHECK_CACHE_SECONDS:
            return self._llm_result
        try:
            self._llm_result = bool(await asyncio.to_thread(llm.check_availability))
        except Exception:
            logger.exception("LLM reachability check failed")
            self._llm_result = False
        self._llm_checked_at = self._clock()
        return self._llm_result
