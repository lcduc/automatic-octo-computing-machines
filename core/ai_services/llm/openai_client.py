"""
Single owner of the OpenAI SDK clients used by the application.

Creating an ``OpenAI``/``AsyncOpenAI`` client opens an HTTP connection pool, so
they are built once and reused for every call instead of being re-created per
request. Availability probing also lives here so it stays a cheap, unbilled
metadata call rather than a chat completion.
"""

# Standard library imports
import logging
import threading
from typing import Any, AsyncIterator, Dict, List, Optional

# Third-party imports
from openai import AsyncOpenAI, OpenAI, APIConnectionError, APIStatusError

# Local imports
from config.settings import Config

logger = logging.getLogger(__name__)


class OpenAIClientProvider:
    """
    Lazily builds and reuses the sync/async OpenAI clients.

    All chat completion traffic goes through :meth:`complete` and
    :meth:`stream` so retry, timeout and model settings are configured once.
    """

    #: Retries performed by the SDK before an error is surfaced.
    MAX_RETRIES = 2

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Override for the configured key, mainly for tests.
        """
        self._api_key = api_key if api_key is not None else Config.LLM.OPENAI_API_KEY()
        self._sync_client: Optional[OpenAI] = None
        self._async_client: Optional[AsyncOpenAI] = None
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        """True when an API key is present."""
        return bool(self._api_key)

    @property
    def sync_client(self) -> OpenAI:
        """Shared blocking client."""
        if self._sync_client is None:
            with self._lock:
                if self._sync_client is None:
                    self._sync_client = OpenAI(
                        api_key=self._api_key,
                        timeout=Config.LLM.OPENAI_TIMEOUT(),
                        max_retries=self.MAX_RETRIES,
                    )
        return self._sync_client

    @property
    def async_client(self) -> AsyncOpenAI:
        """Shared asyncio client used by the streaming path."""
        if self._async_client is None:
            with self._lock:
                if self._async_client is None:
                    self._async_client = AsyncOpenAI(
                        api_key=self._api_key,
                        timeout=Config.LLM.OPENAI_TIMEOUT(),
                        max_retries=self.MAX_RETRIES,
                    )
        return self._async_client

    def check_availability(self) -> bool:
        """
        Probe the API with a free metadata call.

        A 4xx response still means the endpoint is reachable, so it is reported
        as available and the credential problem is surfaced in the log instead
        of blocking startup.

        Returns:
            True when the API is reachable (or reachable but rejecting the key).
        """
        if not self.is_configured:
            logger.warning("OpenAI API key not configured")
            return False
        try:
            self.sync_client.models.list()
            logger.info("OpenAI API available and responding")
            return True
        except APIStatusError as exc:
            logger.warning(
                "OpenAI reachable but returned status %s; check API key/permissions. Detail: %s",
                exc.status_code,
                exc.message,
            )
            return True
        except APIConnectionError:
            logger.exception("OpenAI API unreachable (network/TLS failure)")
            return False
        except Exception:
            logger.exception("Unexpected error while probing the OpenAI API")
            return False

    def complete(self, messages: List[Dict[str, Any]]) -> str:
        """
        Run a blocking chat completion and return the assistant text.

        Args:
            messages: OpenAI-format message list.

        Returns:
            The assistant message content, stripped (empty string if none).
        """
        response = self.sync_client.chat.completions.create(
            model=Config.LLM.OPENAI_MODEL(),
            messages=messages,  # type: ignore[arg-type]
            max_tokens=Config.LLM.OPENAI_MAX_TOKENS(),
            temperature=Config.LLM.OPENAI_TEMPERATURE(),
        )
        content = response.choices[0].message.content
        return content.strip() if content else ""

    async def complete_async(self, messages: List[Dict[str, Any]]) -> str:
        """
        Run a non-blocking chat completion and return the assistant text.

        Async counterpart of :meth:`complete`, used by callers already running
        on the event loop (e.g. batch processing) so they don't block it.

        Args:
            messages: OpenAI-format message list.

        Returns:
            The assistant message content, stripped (empty string if none).
        """
        response = await self.async_client.chat.completions.create(
            model=Config.LLM.OPENAI_MODEL(),
            messages=messages,  # type: ignore[arg-type]
            max_tokens=Config.LLM.OPENAI_MAX_TOKENS(),
            temperature=Config.LLM.OPENAI_TEMPERATURE(),
        )
        content = response.choices[0].message.content
        return content.strip() if content else ""

    async def complete_with_tools_async(
        self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None
    ) -> Any:
        """
        Run a non-streaming chat completion, optionally offering tools to call.

        Unlike :meth:`complete_async`, this returns the raw assistant message
        instead of just its text, so the caller can inspect ``tool_calls``
        before deciding whether to execute anything. ``tools`` is omitted
        from the request entirely when empty, rather than sent as ``[]``.

        Args:
            messages: OpenAI-format message list.
            tools: Tool schemas (``{"type": "function", "function": {...}}``),
                or ``None``/empty to make a plain completion.

        Returns:
            The assistant ``message`` object (``.content``, ``.tool_calls``).
        """
        kwargs: Dict[str, Any] = dict(
            model=Config.LLM.OPENAI_MODEL(),
            messages=messages,
            max_tokens=Config.LLM.OPENAI_MAX_TOKENS(),
            temperature=Config.LLM.OPENAI_TEMPERATURE(),
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = await self.async_client.chat.completions.create(**kwargs)
        return response.choices[0].message

    async def stream(self, messages: List[Dict[str, Any]]) -> AsyncIterator[str]:
        """
        Stream a chat completion, yielding text deltas as they arrive.

        Args:
            messages: OpenAI-format message list.

        Yields:
            Non-empty content deltas.
        """
        response_stream = await self.async_client.chat.completions.create(
            model=Config.LLM.OPENAI_MODEL(),
            messages=messages,  # type: ignore[arg-type]
            max_tokens=Config.LLM.OPENAI_MAX_TOKENS(),
            temperature=Config.LLM.OPENAI_TEMPERATURE(),
            stream=True,
        )
        async for chunk in response_stream:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                yield content

    def close(self) -> None:
        """Close both clients and release their connection pools."""
        for client in (self._sync_client, self._async_client):
            if client is None:
                continue
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    result = close()
                    # AsyncOpenAI.close() returns a coroutine; drop it rather
                    # than await here so shutdown stays synchronous.
                    if hasattr(result, "close"):
                        result.close()
            except Exception:
                logger.exception("Error closing OpenAI client")
        self._sync_client = None
        self._async_client = None
