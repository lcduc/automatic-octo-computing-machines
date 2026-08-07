"""
Single owner of the Anthropic SDK clients used by the application.

Mirrors ``openai_client.py``'s shape: clients are built once and reused so
retry/timeout/model settings are configured in one place, and availability
probing is a cheap metadata call rather than a chat completion.
"""

# Standard library imports
import logging
import threading
from typing import Any, AsyncIterator, Dict, List, Optional

# Third-party imports
from anthropic import Anthropic, AsyncAnthropic, APIConnectionError, APIStatusError

# Local imports
from config.settings import Config
from .base_llm_provider import BaseLLMProvider

logger = logging.getLogger(__name__)


class AnthropicClientProvider(BaseLLMProvider):
    """
    Lazily builds and reuses the sync/async Anthropic clients.

    Anthropic's Messages API takes the system prompt as a separate top-level
    ``system`` parameter rather than a ``role: "system"`` message, so every
    call site here splits it out of the incoming OpenAI-format message list.
    """

    #: Retries performed by the SDK before an error is surfaced.
    MAX_RETRIES = 2

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Override for the configured key, mainly for tests.
        """
        self._api_key = api_key if api_key is not None else Config.LLM.ANTHROPIC_API_KEY()
        self._sync_client: Optional[Anthropic] = None
        self._async_client: Optional[AsyncAnthropic] = None
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        """True when an API key is present."""
        return bool(self._api_key)

    @property
    def sync_client(self) -> Anthropic:
        """Shared blocking client."""
        if self._sync_client is None:
            with self._lock:
                if self._sync_client is None:
                    self._sync_client = Anthropic(
                        api_key=self._api_key,
                        timeout=Config.LLM.ANTHROPIC_TIMEOUT(),
                        max_retries=self.MAX_RETRIES,
                    )
        return self._sync_client

    @property
    def async_client(self) -> AsyncAnthropic:
        """Shared asyncio client used by the streaming path."""
        if self._async_client is None:
            with self._lock:
                if self._async_client is None:
                    self._async_client = AsyncAnthropic(
                        api_key=self._api_key,
                        timeout=Config.LLM.ANTHROPIC_TIMEOUT(),
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
            logger.warning("Anthropic API key not configured")
            return False
        try:
            self.sync_client.models.list()
            logger.info("Anthropic API available and responding")
            return True
        except APIStatusError as exc:
            logger.warning(
                "Anthropic reachable but returned status %s; check API key/permissions. Detail: %s",
                exc.status_code,
                exc.message,
            )
            return True
        except APIConnectionError:
            logger.exception("Anthropic API unreachable (network/TLS failure)")
            return False
        except Exception:
            logger.exception("Unexpected error while probing the Anthropic API")
            return False

    @staticmethod
    def _split_system(messages: List[Dict[str, Any]]) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """
        Pull the leading ``role: "system"`` message out of an OpenAI-format list.

        Anthropic takes the system prompt as a separate top-level parameter;
        any non-leading system-role message is left in place as ordinary
        conversation content rather than silently dropped.

        Returns:
            A ``(system_prompt, remaining_messages)`` pair; ``system_prompt``
            is ``None`` when there is no leading system message.
        """
        if messages and messages[0].get("role") == "system":
            return str(messages[0].get("content", "")), list(messages[1:])
        return None, list(messages)

    def complete(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> str:
        """
        Run a blocking chat completion and return the assistant text.

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.ANTHROPIC_MODEL()``.

        Returns:
            The assistant message text, stripped (empty string if none).
        """
        system, rest = self._split_system(messages)
        response = self.sync_client.messages.create(
            model=model or Config.LLM.ANTHROPIC_MODEL(),
            max_tokens=Config.LLM.ANTHROPIC_MAX_TOKENS(),
            system=system,
            messages=rest,
        )
        text = next((block.text for block in response.content if block.type == "text"), "")
        return text.strip() if text else ""

    async def complete_async(
        self, messages: List[Dict[str, Any]], model: Optional[str] = None
    ) -> str:
        """
        Run a non-blocking chat completion and return the assistant text.

        Async counterpart of :meth:`complete`, used by callers already
        running on the event loop (e.g. batch processing).

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.ANTHROPIC_MODEL()``.

        Returns:
            The assistant message text, stripped (empty string if none).
        """
        system, rest = self._split_system(messages)
        response = await self.async_client.messages.create(
            model=model or Config.LLM.ANTHROPIC_MODEL(),
            max_tokens=Config.LLM.ANTHROPIC_MAX_TOKENS(),
            system=system,
            messages=rest,
        )
        text = next((block.text for block in response.content if block.type == "text"), "")
        return text.strip() if text else ""

    async def stream(
        self, messages: List[Dict[str, Any]], model: Optional[str] = None
    ) -> AsyncIterator[str]:
        """
        Stream a chat completion, yielding text deltas as they arrive.

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.ANTHROPIC_MODEL()``.

        Yields:
            Non-empty text deltas.
        """
        system, rest = self._split_system(messages)
        async with self.async_client.messages.stream(
            model=model or Config.LLM.ANTHROPIC_MODEL(),
            max_tokens=Config.LLM.ANTHROPIC_MAX_TOKENS(),
            system=system,
            messages=rest,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text

    def close(self) -> None:
        """Close both clients and release their connection pools."""
        for client in (self._sync_client, self._async_client):
            if client is None:
                continue
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    result = close()
                    # AsyncAnthropic.close() returns a coroutine; drop it rather
                    # than await here so shutdown stays synchronous.
                    if hasattr(result, "close"):
                        result.close()
            except Exception:
                logger.exception("Error closing Anthropic client")
        self._sync_client = None
        self._async_client = None
