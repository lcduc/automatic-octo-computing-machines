"""Chat calls send the parameter set the configured model family accepts."""

from core.ai_services.llm.chatbot import completion_kwargs


def test_newer_models_get_max_completion_tokens_and_reasoning_effort(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "4000")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")

    assert completion_kwargs() == {
        "model": "gpt-5-mini",
        "max_completion_tokens": 4000,
        "extra_body": {"reasoning_effort": "low"},
    }


def test_an_empty_reasoning_effort_is_left_to_the_model(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-luna")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "")

    assert "extra_body" not in completion_kwargs() and "temperature" not in completion_kwargs()


def test_legacy_models_keep_max_tokens_and_temperature(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "500")
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.2")

    assert completion_kwargs() == {"model": "gpt-4.1-mini", "max_tokens": 500, "temperature": 0.2}
