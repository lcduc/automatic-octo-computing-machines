"""Unit tests for voice-query transcription across the OpenAIClientProvider,
ChatbotService and ChatService layers."""

import pytest

from core.ai_services.llm.chatbot import ChatbotService
from core.ai_services.llm.openai_client import OpenAIClientProvider
from services.chat_service import ChatService


class _FakeTranscriptions:
    """Records calls made to ``audio.transcriptions.create`` instead of hitting the API."""

    def __init__(self, response: str = "", raise_error: bool = False):
        self.response = response
        self.raise_error = raise_error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_error:
            raise RuntimeError("simulated API failure")
        return self.response


class _FakeSyncClient:
    def __init__(self, transcriptions: _FakeTranscriptions):
        self.audio = type("_Audio", (), {"transcriptions": transcriptions})()


def _provider_with_fake_transcriptions(transcriptions: _FakeTranscriptions) -> OpenAIClientProvider:
    provider = OpenAIClientProvider(api_key="test-key")
    provider._sync_client = _FakeSyncClient(transcriptions)
    return provider


# ---------------------------------------------------------------------------
# OpenAIClientProvider.transcribe
# ---------------------------------------------------------------------------


def test_transcribe_strips_and_returns_text():
    transcriptions = _FakeTranscriptions(response="  hello world  ")
    provider = _provider_with_fake_transcriptions(transcriptions)

    result = provider.transcribe(b"raw-audio-bytes", "recording.wav", "audio/wav")

    assert result == "hello world"
    assert len(transcriptions.calls) == 1
    kwargs = transcriptions.calls[0]
    assert kwargs["file"] == ("recording.wav", b"raw-audio-bytes", "audio/wav")
    assert kwargs["response_format"] == "text"


def test_transcribe_defaults_to_configured_language_when_omitted():
    transcriptions = _FakeTranscriptions(response="xin chào")
    provider = _provider_with_fake_transcriptions(transcriptions)

    provider.transcribe(b"raw", "clip.wav", "audio/wav")

    assert transcriptions.calls[0]["language"] == "vi"


def test_transcribe_passes_language_hint_when_given():
    transcriptions = _FakeTranscriptions(response="xin chào")
    provider = _provider_with_fake_transcriptions(transcriptions)

    provider.transcribe(b"raw", "clip.wav", "audio/wav", language="fr")

    assert transcriptions.calls[0]["language"] == "fr"


def test_transcribe_empty_string_language_opts_out_of_default():
    transcriptions = _FakeTranscriptions(response="hello")
    provider = _provider_with_fake_transcriptions(transcriptions)

    provider.transcribe(b"raw", "clip.wav", "audio/wav", language="")

    assert "language" not in transcriptions.calls[0]


def test_transcribe_defaults_to_configured_prompt_when_omitted():
    transcriptions = _FakeTranscriptions(response="xin chào")
    provider = _provider_with_fake_transcriptions(transcriptions)

    provider.transcribe(b"raw", "clip.wav", "audio/wav")

    assert "prompt" in transcriptions.calls[0]
    assert transcriptions.calls[0]["prompt"]


def test_transcribe_passes_prompt_override_when_given():
    transcriptions = _FakeTranscriptions(response="xin chào")
    provider = _provider_with_fake_transcriptions(transcriptions)

    provider.transcribe(b"raw", "clip.wav", "audio/wav", prompt="custom vocabulary hint")

    assert transcriptions.calls[0]["prompt"] == "custom vocabulary hint"


def test_transcribe_empty_string_prompt_opts_out_of_default():
    transcriptions = _FakeTranscriptions(response="hello")
    provider = _provider_with_fake_transcriptions(transcriptions)

    provider.transcribe(b"raw", "clip.wav", "audio/wav", prompt="")

    assert "prompt" not in transcriptions.calls[0]


def test_transcribe_returns_empty_string_for_empty_response():
    transcriptions = _FakeTranscriptions(response="")
    provider = _provider_with_fake_transcriptions(transcriptions)

    assert provider.transcribe(b"raw", "clip.wav") == ""


# ---------------------------------------------------------------------------
# ChatbotService.transcribe_audio
# ---------------------------------------------------------------------------


class _StubClientProvider:
    """Fake OpenAIClientProvider that records transcribe() calls."""

    def __init__(self, response: str = "transcribed text", available: bool = True):
        self.response = response
        self.available = available
        self.calls = []

    def check_availability(self) -> bool:
        return self.available

    def transcribe(self, audio_bytes, filename, content_type):
        self.calls.append((audio_bytes, filename, content_type))
        return self.response


@pytest.mark.asyncio
async def test_chatbot_service_transcribe_audio_delegates_to_client_provider():
    client = _StubClientProvider(response="what is the refund policy")
    service = ChatbotService(context_retriever=object(), llm_provider=client)

    result = await service.transcribe_audio(b"raw-bytes", "voice.wav", "audio/wav")

    assert result == "what is the refund policy"
    assert client.calls == [(b"raw-bytes", "voice.wav", "audio/wav")]


# ---------------------------------------------------------------------------
# ChatService.transcribe_audio
# ---------------------------------------------------------------------------


class _StubChatbotService:
    def __init__(self, response: str = "transcribed", available: bool = True):
        self.response = response
        self.api_available = available
        self.calls = []

    async def transcribe_audio(self, audio_bytes, filename, content_type):
        self.calls.append((audio_bytes, filename, content_type))
        return self.response


@pytest.mark.asyncio
async def test_chat_service_transcribe_audio_delegates_when_available():
    chatbot = _StubChatbotService(response="hello there")
    service = ChatService(chatbot_service=chatbot)

    result = await service.transcribe_audio(b"raw", "clip.wav", "audio/wav")

    assert result == "hello there"
    assert chatbot.calls == [(b"raw", "clip.wav", "audio/wav")]


@pytest.mark.asyncio
async def test_chat_service_transcribe_audio_raises_when_unavailable():
    chatbot = _StubChatbotService(available=False)
    service = ChatService(chatbot_service=chatbot)

    with pytest.raises(RuntimeError):
        await service.transcribe_audio(b"raw", "clip.wav", "audio/wav")

    assert chatbot.calls == []
