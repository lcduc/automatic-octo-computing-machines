"""
Single owner of the Google Gen AI SDK client used by the application.

Uses the stable ``client.models.generate_content`` surface (and its ``.aio``
async counterpart) rather than the newer, stateful Interactions API: this
app resends the full conversation history on every request (see
``api/routes/chat.py``), which is exactly the stateless shape
``generate_content`` is built for, whereas the Interactions API is designed
around server-side ``previous_interaction_id`` continuation.
"""

# Standard library imports
import logging
import threading
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

# Third-party imports
from google import genai
from google.genai import errors, types

# Local imports
from config.settings import Config
from models.llm import LLMResult, LLMUsage, StreamDelta
from .base_llm_provider import BaseLLMProvider

logger = logging.getLogger(__name__)

#: Gemini's role name for assistant turns; the app's message lists use "assistant".
_MODEL_ROLE = "model"

#: ``HttpOptions.timeout`` is expressed in milliseconds.
MILLISECONDS_PER_SECOND = 1000


class GeminiClientProvider(BaseLLMProvider):
    """
    Lazily builds and reuses the Gemini client.

    The SDK's single ``genai.Client`` exposes both the blocking surface
    (``client.models``) and the asyncio surface (``client.aio.models``), so
    unlike the OpenAI/Anthropic providers there is only one client to own.
    """

    name = "gemini"

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Override for the configured key, mainly for tests.
        """
        self._api_key = api_key if api_key is not None else Config.LLM.GEMINI_API_KEY()
        self._client: Optional[genai.Client] = None
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        """True when an API key is present."""
        return bool(self._api_key)

    @property
    def client(self) -> genai.Client:
        """Shared client (exposes both the sync and ``.aio`` async surfaces)."""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = genai.Client(
                        api_key=self._api_key,
                        http_options=types.HttpOptions(
                            timeout=Config.LLM.GEMINI_TIMEOUT() * MILLISECONDS_PER_SECOND
                        ),
                    )
        return self._client

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
            logger.warning("Gemini API key not configured")
            return False
        try:
            next(iter(self.client.models.list()), None)
            logger.info("Gemini API available and responding")
            return True
        except errors.APIError as exc:
            if exc.code and 400 <= exc.code < 500:
                logger.warning(
                    "Gemini reachable but returned status %s; check API key/permissions. Detail: %s",
                    exc.code,
                    exc.message,
                )
                return True
            logger.exception("Gemini API error while probing availability")
            return False
        except Exception:
            logger.exception("Unexpected error while probing the Gemini API")
            return False

    @staticmethod
    def _to_contents(
        messages: List[Dict[str, Any]],
    ) -> Tuple[Optional[str], List[types.Content]]:
        """
        Convert an OpenAI-format message list into Gemini's ``contents`` shape.

        Gemini has no system role inside ``contents``; any leading
        ``role: "system"`` message is pulled out for ``system_instruction``
        instead. ``"assistant"`` is renamed to Gemini's ``"model"`` role.

        Returns:
            A ``(system_instruction, contents)`` pair; ``system_instruction``
            is ``None`` when there is no leading system message.
        """
        system_instruction: Optional[str] = None
        rest = messages
        if messages and messages[0].get("role") == "system":
            system_instruction = str(messages[0].get("content", ""))
            rest = messages[1:]

        contents: List[types.Content] = []
        for message in rest:
            role = _MODEL_ROLE if message.get("role") == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=str(message.get("content", "")))])
            )
        return system_instruction, contents

    @staticmethod
    def _build_config(system_instruction: Optional[str]) -> types.GenerateContentConfig:
        """Assemble the shared generation config for one request."""
        return types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=Config.LLM.GEMINI_MAX_TOKENS(),
        )

    def _usage(self, model: str, metadata: Any) -> Optional[LLMUsage]:
        """
        Convert ``usage_metadata`` into :class:`LLMUsage`.

        Thinking tokens are billed as output, so they count as completion tokens.
        """
        if metadata is None:
            return None
        completion = (getattr(metadata, "candidates_token_count", 0) or 0) + (
            getattr(metadata, "thoughts_token_count", 0) or 0
        )
        return LLMUsage(
            provider=self.name,
            model=model,
            prompt_tokens=int(getattr(metadata, "prompt_token_count", 0) or 0),
            completion_tokens=int(completion),
        )

    @staticmethod
    def _safe_text(response: Any) -> str:
        """
        Text of a response, or ``""`` when the candidate was blocked.

        ``response.text`` is ``None`` (or raises) for safety-blocked or empty
        candidates; that must degrade to an empty answer, not a crash.
        """
        try:
            return response.text or ""
        except Exception:
            logger.warning("Gemini returned no usable text (blocked or empty candidate)")
            return ""

    def complete(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> LLMResult:
        """
        Run a blocking chat completion.

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.GEMINI_MODEL()``.
        """
        system_instruction, contents = self._to_contents(messages)
        resolved_model = model or Config.LLM.GEMINI_MODEL()
        response = self.client.models.generate_content(
            model=resolved_model, contents=contents, config=self._build_config(system_instruction)
        )
        return LLMResult(self._safe_text(response).strip(), self._usage(resolved_model, response.usage_metadata))

    async def complete_async(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> LLMResult:
        """
        Run a non-blocking chat completion.

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.GEMINI_MODEL()``.
        """
        system_instruction, contents = self._to_contents(messages)
        resolved_model = model or Config.LLM.GEMINI_MODEL()
        response = await self.client.aio.models.generate_content(
            model=resolved_model, contents=contents, config=self._build_config(system_instruction)
        )
        return LLMResult(self._safe_text(response).strip(), self._usage(resolved_model, response.usage_metadata))

    async def stream(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> AsyncIterator[StreamDelta]:
        """
        Stream a chat completion.

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.GEMINI_MODEL()``.

        Yields:
            Non-empty text deltas, then one delta with the last reported usage.
        """
        system_instruction, contents = self._to_contents(messages)
        resolved_model = model or Config.LLM.GEMINI_MODEL()
        response_stream = await self.client.aio.models.generate_content_stream(
            model=resolved_model, contents=contents, config=self._build_config(system_instruction)
        )
        usage_metadata = None
        async for chunk in response_stream:
            if chunk.usage_metadata is not None:
                usage_metadata = chunk.usage_metadata
            text = self._safe_text(chunk)
            if text:
                yield StreamDelta(text=text)
        yield StreamDelta(usage=self._usage(resolved_model, usage_metadata))

    def close(self) -> None:
        """
        No-op: the Gen AI SDK client holds no persistent connection pool to release.
        """
        self._client = None
