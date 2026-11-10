"""Unit tests for voice-query transcription: OpenAIClientProvider and TranscriptionService."""

import pytest

from core.agent.openai_client import OpenAIClientProvider
from services.errors import ServiceUnavailableError
from services.transcription_service import TranscriptionService


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
# TranscriptionService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcription_service_delegates_to_provider():
    transcriptions = _FakeTranscriptions(response="xin chào")
    service = TranscriptionService(_provider_with_fake_transcriptions(transcriptions))

    assert await service.transcribe(b"raw", "clip.webm", "audio/webm") == "xin chào"
    assert transcriptions.calls[0]["file"] == ("clip.webm", b"raw", "audio/webm")


@pytest.mark.asyncio
async def test_transcription_service_unavailable_without_openai_key():
    with pytest.raises(ServiceUnavailableError):
        await TranscriptionService(None).transcribe(b"raw", "clip.webm", "audio/webm")
    with pytest.raises(ServiceUnavailableError):
        await TranscriptionService(OpenAIClientProvider(api_key="")).transcribe(b"raw", "clip.webm", "audio/webm")
