"""
Speech-to-text for voice questions (OpenAI transcription API).
"""

# Standard library imports
import asyncio
import logging
from typing import Optional

# Local imports
from core.agent.openai_client import OpenAIClientProvider
from .errors import ServiceUnavailableError

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Transcribes audio clips; only available when an OpenAI key is configured."""

    def __init__(self, provider: Optional[OpenAIClientProvider]):
        """
        Args:
            provider: OpenAI provider, or ``None`` when no key is configured.
        """
        self._provider = provider

    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        """
        Transcribe one clip in a worker thread.

        Raises:
            ServiceUnavailableError: No OpenAI key is configured.
        """
        if self._provider is None or not self._provider.is_configured:
            raise ServiceUnavailableError("Voice input is not available")
        logger.info("Transcribing %s (%d bytes)", filename, len(audio))
        return await asyncio.to_thread(self._provider.transcribe, audio, filename, content_type)
