"""
Selects the active LLM provider based on configuration.

This is the one place in the codebase that knows about every concrete
:class:`BaseLLMProvider` implementation; everything else (``ChatbotService``,
``QueryRewriter``, ``IntentRouter``) depends only on the abstraction.
"""

# Standard library imports
import logging

# Local imports
from config.settings import Config
from .anthropic_client import AnthropicClientProvider
from .base_llm_provider import BaseLLMProvider
from .gemini_client import GeminiClientProvider
from .openai_client import OpenAIClientProvider

logger = logging.getLogger(__name__)


class LLMProviderFactory:
    """Builds the :class:`BaseLLMProvider` selected by ``Config.LLM.LLM_PROVIDER()``."""

    @staticmethod
    def create() -> BaseLLMProvider:
        """
        Instantiate the configured chat-completion provider.

        Returns:
            An :class:`AnthropicClientProvider`, :class:`GeminiClientProvider`,
            or :class:`OpenAIClientProvider`, depending on ``LLM_PROVIDER``.
            Unrecognized values fall back to OpenAI with a logged warning.
        """
        provider = Config.LLM.LLM_PROVIDER().strip().lower()
        if provider == "anthropic":
            return AnthropicClientProvider()
        if provider == "gemini":
            return GeminiClientProvider()
        if provider != "openai":
            logger.warning("Unknown LLM_PROVIDER=%r; defaulting to openai", provider)
        return OpenAIClientProvider()
