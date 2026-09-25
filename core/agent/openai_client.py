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
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

# Third-party imports
from openai import AsyncOpenAI, OpenAI, APIConnectionError, APIStatusError

# Local imports
from config.settings import Config
from models.llm import LLMResult, LLMUsage, StreamDelta
from .base_llm_provider import BaseLLMProvider
from .prompts import SystemPrompts

logger = logging.getLogger(__name__)


class OpenAIClientProvider(BaseLLMProvider):
    """
    Lazily builds and reuses the sync/async OpenAI clients.

    All chat completion traffic goes through :meth:`complete` and
    :meth:`stream` so retry, timeout and model settings are configured once.
    Also owns tool-calling (:meth:`complete_with_tools_async`) and
    speech-to-text (:meth:`transcribe`) — capabilities specific to this
    provider and not part of :class:`BaseLLMProvider`.
    """

    name = "openai"

    #: Retries performed by the SDK before an error is surfaced.
    MAX_RETRIES = 2
    #: Free moderation model used by the input guard.
    MODERATION_MODEL = "omni-moderation-latest"

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

    @staticmethod
    def _completion_kwargs(
        model: str, max_tokens: int, temperature: float, reasoning_effort: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build the model/token-limit/temperature kwargs for a completion call.

        ``gpt-5*`` models reject the legacy ``max_tokens`` parameter (they need
        ``max_completion_tokens`` instead) and only support the default
        ``temperature`` of 1, so both are adapted per model family here rather
        than at each call site.

        ``reasoning_effort`` is a real parameter for ``gpt-5*`` models, but the
        ``openai`` SDK version this project is pinned to (see
        ``requirements.txt``) predates that parameter's addition to
        ``chat.completions.create``'s typed signature and raises
        ``TypeError: unexpected keyword argument 'reasoning_effort'`` if passed
        directly. The API itself accepts it as a plain JSON body field
        regardless of the installed SDK's parameter list, so it is sent via
        ``extra_body`` instead — a raw-payload escape hatch the SDK has
        supported since its first Stainless-generated release. Switch this to
        a direct keyword once the pin is upgraded to a version whose
        ``create()`` signature includes it natively.

        Args:
            model: Model name to resolve the parameter set for.
            max_tokens: Completion token cap.
            temperature: Sampling temperature; dropped for ``gpt-5*`` models.
            reasoning_effort: One of ``none/minimal/low/medium/high/xhigh/max``
                (model-dependent); ignored for non-``gpt-5*`` models, and
                omitted entirely when falsy.

        Returns:
            Kwargs ready to splat into ``chat.completions.create``.
        """
        kwargs: Dict[str, Any] = {"model": model}
        if model.startswith("gpt-5"):
            kwargs["max_completion_tokens"] = max_tokens
            if reasoning_effort:
                kwargs["extra_body"] = {"reasoning_effort": reasoning_effort}
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = temperature
        return kwargs

    def _usage(self, model: str, usage: Any) -> Optional[LLMUsage]:
        """Convert the SDK's ``CompletionUsage`` into :class:`LLMUsage`."""
        if usage is None:
            return None
        return LLMUsage(
            provider=self.name,
            model=model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )

    def _default_kwargs(self, model: Optional[str]) -> Dict[str, Any]:
        """Completion kwargs for ``model`` (the configured answer model by default)."""
        return self._completion_kwargs(
            model or Config.LLM.OPENAI_MODEL(),
            Config.LLM.OPENAI_MAX_TOKENS(),
            Config.LLM.OPENAI_TEMPERATURE(),
            Config.LLM.OPENAI_REASONING_EFFORT(),
        )

    def complete(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> LLMResult:
        """
        Run a blocking chat completion.

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.OPENAI_MODEL()``.

        Returns:
            The stripped assistant text and its token usage.
        """
        kwargs = self._default_kwargs(model)
        response = self.sync_client.chat.completions.create(messages=messages, **kwargs)  # type: ignore[arg-type]
        content = response.choices[0].message.content
        return LLMResult(content.strip() if content else "", self._usage(kwargs["model"], response.usage))

    async def complete_async(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> LLMResult:
        """
        Run a non-blocking chat completion.

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.OPENAI_MODEL()``.

        Returns:
            The stripped assistant text and its token usage.
        """
        kwargs = self._default_kwargs(model)
        response = await self.async_client.chat.completions.create(messages=messages, **kwargs)  # type: ignore[arg-type]
        content = response.choices[0].message.content
        return LLMResult(content.strip() if content else "", self._usage(kwargs["model"], response.usage))

    async def moderate(self, text: str) -> bool:
        """
        Screen text with OpenAI's moderation endpoint (free of charge).

        Returns:
            True when the text is flagged as harmful.
        """
        response = await self.async_client.moderations.create(model=self.MODERATION_MODEL, input=text)
        return any(result.flagged for result in response.results)

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str = "audio/wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe a recorded audio clip to text via the speech-to-text endpoint.

        Args:
            audio_bytes: Raw audio file content (wav/mp3/m4a/webm/...).
            filename: Original filename; its extension hints the audio format
                to the API, which does not otherwise inspect the bytes.
            content_type: MIME type reported by the client.
            language: ISO-639-1 language hint; defaults to
                ``Config.LLM.TRANSCRIPTION_LANGUAGE()`` when omitted. Pass
                ``""`` explicitly to let the model auto-detect instead.
            prompt: Style/vocabulary hint that also steers the output
                language on ambiguous audio; defaults to
                ``SystemPrompts.TRANSCRIPTION`` when omitted. Pass
                ``""`` explicitly to send none.

        Returns:
            The transcribed text, stripped.
        """
        kwargs: Dict[str, Any] = dict(
            model=Config.LLM.TRANSCRIPTION_MODEL(),
            file=(filename, audio_bytes, content_type),
            response_format="text",
        )
        resolved_language = (
            language if language is not None else Config.LLM.TRANSCRIPTION_LANGUAGE()
        )
        if resolved_language:
            kwargs["language"] = resolved_language
        resolved_prompt = prompt if prompt is not None else SystemPrompts.TRANSCRIPTION
        if resolved_prompt:
            kwargs["prompt"] = resolved_prompt
        text = self.sync_client.audio.transcriptions.create(**kwargs)
        return text.strip() if text else ""

    async def complete_with_tools_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
    ) -> Tuple[Any, Optional[LLMUsage]]:
        """
        Run a non-streaming chat completion, optionally offering tools to call.

        Returns the raw assistant message (not just its text) so the caller can
        inspect ``tool_calls``. ``tools`` is omitted from the request when empty.

        Args:
            messages: OpenAI-format message list.
            tools: Tool schemas, or ``None``/empty for a plain completion.
            model: Model override; defaults to ``Config.LLM.OPENAI_MODEL()``.

        Returns:
            ``(assistant_message, usage)``.
        """
        kwargs: Dict[str, Any] = dict(messages=messages, **self._default_kwargs(model))
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = await self.async_client.chat.completions.create(**kwargs)
        return response.choices[0].message, self._usage(kwargs["model"], response.usage)

    async def stream(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> AsyncIterator[StreamDelta]:
        """
        Stream a chat completion.

        Args:
            messages: OpenAI-format message list.
            model: Model override; defaults to ``Config.LLM.OPENAI_MODEL()``.

        Yields:
            Non-empty text deltas, then one delta with the usage reported in
            the final chunk (``stream_options.include_usage``).
        """
        kwargs = self._default_kwargs(model)
        response_stream = await self.async_client.chat.completions.create(
            messages=messages,  # type: ignore[arg-type]
            stream=True,
            stream_options={"include_usage": True},
            **kwargs,
        )
        async for chunk in response_stream:
            if chunk.usage is not None:
                yield StreamDelta(usage=self._usage(kwargs["model"], chunk.usage))
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                yield StreamDelta(text=content)

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
