"""OpenAIClientProvider can target an OpenAI-compatible server through OPENAI_BASE_URL."""

from core.agent.openai_client import LOCAL_SERVER_API_KEY, OpenAIClientProvider

LOCAL_URL = "http://localhost:11434/v1"


def test_base_url_reaches_both_clients_and_key_may_be_empty():
    provider = OpenAIClientProvider(api_key="", base_url=LOCAL_URL)

    assert provider.is_configured
    assert str(provider.sync_client.base_url).rstrip("/") == LOCAL_URL
    assert str(provider.async_client.base_url).rstrip("/") == LOCAL_URL
    assert provider.sync_client.api_key == LOCAL_SERVER_API_KEY


def test_without_base_url_or_key_provider_is_unconfigured():
    assert not OpenAIClientProvider(api_key="", base_url="").is_configured


def test_default_endpoint_is_openai_when_no_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    provider = OpenAIClientProvider(api_key="sk-test")

    assert "api.openai.com" in str(provider.sync_client.base_url)
