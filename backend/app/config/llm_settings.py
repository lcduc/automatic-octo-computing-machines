"""
LLM settings: provider selection, credentials, model selection and answer-cache tuning.

Read through :class:`app.config.settings.Config` (``Config.LLM``).
"""

# Standard library imports
import os
from typing import Optional

# Local imports
from .env import env_bool, env_float, env_int, env_str

#: ``LLM_PROVIDER`` value of the deterministic load-test provider (``core/agent/stub_client.py``).
STUB_PROVIDER = "stub"
#: Model name the stub reports for both the main and the light model.
STUB_MODEL = "stub"


class LLMConfig:
    """LLM provider selection, credentials, model selection and answer-cache tuning."""

    @staticmethod
    def LLM_PROVIDER() -> str:
        """
        Which chat-completion backend to use: ``openai``, ``anthropic`` or ``gemini``.

        ``stub`` selects canned tokens for load tests; production refuses to start with it.
        """
        return env_str("LLM_PROVIDER", "openai")

    @staticmethod
    def ACTIVE_MODEL() -> str:
        """Main answer-generation model for whichever provider is active."""
        provider = LLMConfig.LLM_PROVIDER().strip().lower()
        if provider == STUB_PROVIDER:
            return STUB_MODEL
        if provider == "anthropic":
            return LLMConfig.ANTHROPIC_MODEL()
        if provider == "gemini":
            return LLMConfig.GEMINI_MODEL()
        return LLMConfig.OPENAI_MODEL()

    @staticmethod
    def ACTIVE_LIGHT_MODEL() -> str:
        """Cheap/fast model (query rewriting, intent classification) for the active provider."""
        provider = LLMConfig.LLM_PROVIDER().strip().lower()
        if provider == STUB_PROVIDER:
            return STUB_MODEL
        if provider == "anthropic":
            return LLMConfig.ANTHROPIC_LIGHT_MODEL()
        if provider == "gemini":
            return LLMConfig.GEMINI_LIGHT_MODEL()
        return LLMConfig.OPENAI_LIGHT_MODEL()

    @staticmethod
    def ACTIVE_API_KEY() -> Optional[str]:
        """API key for whichever provider ``LLM_PROVIDER`` selects."""
        provider = LLMConfig.LLM_PROVIDER().strip().lower()
        if provider == "anthropic":
            return LLMConfig.ANTHROPIC_API_KEY()
        if provider == "gemini":
            return LLMConfig.GEMINI_API_KEY()
        return LLMConfig.OPENAI_API_KEY()

    @staticmethod
    def OPENAI_API_KEY() -> Optional[str]:
        """API key; ``None`` when unset so callers can degrade gracefully."""
        return os.getenv("OPENAI_API_KEY") or None

    @staticmethod
    def OPENAI_BASE_URL() -> Optional[str]:
        """
        Endpoint of an OpenAI-compatible server (vLLM, Ollama, ...); ``None`` means api.openai.com.

        With it set the key may stay empty, since local servers usually ignore it.
        """
        return os.getenv("OPENAI_BASE_URL") or None

    @staticmethod
    def OPENAI_MODEL() -> str:
        """Chat completion model used for answer generation."""
        return env_str("OPENAI_MODEL", "gpt-5-mini")

    @staticmethod
    def OPENAI_LIGHT_MODEL() -> str:
        """Cheaper model for lightweight judgment calls (query rewriting, intent classification)."""
        return env_str("OPENAI_LIGHT_MODEL", "gpt-4.1-nano")

    @staticmethod
    def TOOL_CALLING_ENABLED() -> bool:
        """
        Route chat turns through ``IntentRouter``/``ToolCallingAgent``.

        Every turn otherwise pays for an extra intent-classification call, so
        this can disable the action engine without a redeploy.
        """
        return env_bool("TOOL_CALLING_ENABLED", False)

    @staticmethod
    def EMBEDDING_MODEL() -> str:
        """Sentence-transformers model used to embed chunks and queries."""
        return env_str("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

    @staticmethod
    def MAX_CONTEXT_LENGTH() -> int:
        """Character budget for the retrieved context block."""
        return env_int("MAX_CONTEXT_LENGTH", 6000)

    @staticmethod
    def OPENAI_MAX_TOKENS() -> int:
        """Completion token cap per request."""
        return env_int("OPENAI_MAX_TOKENS", 4000)

    @staticmethod
    def OPENAI_TEMPERATURE() -> float:
        """
        Sampling temperature for answer generation.

        Ignored for everything newer than ``gpt-4*``, which only supports the default
        temperature of 1 - see ``OpenAIClientProvider._completion_kwargs``.
        """
        return env_float("OPENAI_TEMPERATURE", 0.1)

    @staticmethod
    def OPENAI_REASONING_EFFORT() -> str:
        """
        Reasoning depth for models newer than ``gpt-4*`` (gpt-5+, o-series).

        Which values are accepted is model-dependent and enforced server-side
        (``gpt-5-mini`` accepts ``minimal``/``low``/``medium``/``high``).
        Ignored for non-reasoning models - see
        ``OpenAIClientProvider._completion_kwargs``.
        """
        return env_str("OPENAI_REASONING_EFFORT", "low")

    @staticmethod
    def OPENAI_TIMEOUT() -> int:
        """Per-request timeout in seconds."""
        return env_int("OPENAI_TIMEOUT", 30)

    @staticmethod
    def TRANSCRIPTION_MODEL() -> str:
        """Speech-to-text model used to transcribe voice queries."""
        return env_str("TRANSCRIPTION_MODEL", "gpt-transcribe")

    @staticmethod
    def TRANSCRIPTION_LANGUAGE() -> str:
        """ISO-639-1 language hint for voice queries; empty lets the model auto-detect."""
        return env_str("TRANSCRIPTION_LANGUAGE", "vi")

    @staticmethod
    def ANTHROPIC_API_KEY() -> Optional[str]:
        """API key; ``None`` when unset so callers can degrade gracefully."""
        return os.getenv("ANTHROPIC_API_KEY") or None

    @staticmethod
    def ANTHROPIC_MODEL() -> str:
        """Chat completion model used for answer generation."""
        return env_str("ANTHROPIC_MODEL", "claude-sonnet-5")

    @staticmethod
    def ANTHROPIC_LIGHT_MODEL() -> str:
        """Cheaper model for lightweight judgment calls."""
        return env_str("ANTHROPIC_LIGHT_MODEL", "claude-haiku-4-5")

    @staticmethod
    def ANTHROPIC_MAX_TOKENS() -> int:
        """Completion token cap per request."""
        return env_int("ANTHROPIC_MAX_TOKENS", 4000)

    @staticmethod
    def ANTHROPIC_TIMEOUT() -> int:
        """Per-request timeout in seconds."""
        return env_int("ANTHROPIC_TIMEOUT", 30)

    @staticmethod
    def GEMINI_API_KEY() -> Optional[str]:
        """API key; ``None`` when unset so callers can degrade gracefully."""
        return os.getenv("GEMINI_API_KEY") or None

    @staticmethod
    def GEMINI_MODEL() -> str:
        """Chat completion model used for answer generation."""
        return env_str("GEMINI_MODEL", "gemini-3.6-flash")

    @staticmethod
    def GEMINI_LIGHT_MODEL() -> str:
        """Cheaper model for lightweight judgment calls."""
        return env_str("GEMINI_LIGHT_MODEL", "gemini-3.5-flash-lite")

    @staticmethod
    def GEMINI_MAX_TOKENS() -> int:
        """Completion token cap per request."""
        return env_int("GEMINI_MAX_TOKENS", 4000)

    @staticmethod
    def GEMINI_TIMEOUT() -> int:
        """Per-request timeout in seconds."""
        return env_int("GEMINI_TIMEOUT", 30)

    @staticmethod
    def LLM_CACHE_TTL() -> int:
        """Lifetime of a cached answer, in seconds."""
        return env_int("LLM_CACHE_TTL", 3600)

    @staticmethod
    def LLM_CACHE_MAX_ENTRIES() -> int:
        """Maximum answers held by the in-process LLM cache."""
        return env_int("LLM_CACHE_MAX_ENTRIES", 1000)

    @staticmethod
    def TURN_TIMEOUT_SECONDS() -> int:
        """Hard deadline for one whole chat turn (retrieval + all LLM calls)."""
        return env_int("TURN_TIMEOUT_SECONDS", 90)

    @staticmethod
    def STUB_LLM_TTFT_MS() -> int:
        """``LLM_PROVIDER=stub``: milliseconds before the first streamed token."""
        return env_int("STUB_LLM_TTFT_MS", 400)

    @staticmethod
    def STUB_LLM_TOKEN_DELAY_MS() -> int:
        """``LLM_PROVIDER=stub``: milliseconds between later tokens."""
        return env_int("STUB_LLM_TOKEN_DELAY_MS", 25)

    @staticmethod
    def STUB_LLM_TOKENS() -> int:
        """``LLM_PROVIDER=stub``: tokens per streamed answer."""
        return env_int("STUB_LLM_TOKENS", 60)
