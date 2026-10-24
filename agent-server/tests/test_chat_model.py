from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from server.config.schemas import ModelCredentials, ModelSettings
from server.infrastructure.llm import chat
from server.infrastructure.llm.quota import model_quota_scope
from server.runtimes.repository.model_runtime import close_model_clients


@pytest.mark.parametrize("provider, native, url", [
    ("gemini", "google_genai", None), ("google", "google_genai", None),
    ("openrouter", "openai", "https://openrouter.ai/api/v1"),
    ("groq", "openai", "https://api.groq.com/openai/v1"),
    ("openai", "openai", None), ("anthropic", "anthropic", None),
])
def test_native_chat_model_uses_existing_providers_without_sdk_retries(monkeypatch, provider, native, url):
    factory = Mock()
    monkeypatch.setattr(chat, "init_chat_model", factory)
    settings = ModelSettings(provider=provider, name="offline", temperature=0.3, max_tokens=1000)
    chat.build_chat_model(settings, ModelCredentials(api_key="key"))
    options = {"model_provider": native, "api_key": "key", "temperature": 0.3, "max_tokens": 1000, "max_retries": 0}
    if url:
        options["base_url"] = url
    factory.assert_called_once_with("offline", **options)


def test_native_client_cleanup_deduplicates_aliases():
    import asyncio

    sync_client = SimpleNamespace(close=Mock())
    async_client = SimpleNamespace(aclose=AsyncMock())
    llm = SimpleNamespace(root_client=sync_client, client=sync_client, async_client=async_client)
    assert asyncio.run(close_model_clients(SimpleNamespace(llm=llm))) == ()
    sync_client.close.assert_called_once()
    async_client.aclose.assert_awaited_once()


@pytest.mark.parametrize("provider, name, field", [
    ("gemini", "gemini-2.5-flash", "max_output_tokens"), ("openai", "gpt-4o-mini", "max_tokens"),
])
def test_native_limits_use_real_provider_fields_without_call_time_max_tokens(provider, name, field):
    import asyncio

    model = chat.build_chat_model(ModelSettings(provider=provider, name=name, max_tokens=700, temperature=0.2),
        ModelCredentials(api_key="offline-placeholder"))
    try:
        prepared, options, output_limit = chat.prepare_chat_model(model,
            max_output_tokens=4000, request_timeout_seconds=20)
        assert getattr(prepared, field) == output_limit == 4000
        assert model_quota_scope(prepared) == model_quota_scope(model)
        assert options == {}
        timeout_field = "timeout" if provider == "gemini" else "request_timeout"
        assert getattr(prepared, timeout_field) == 20
        assert getattr(model, timeout_field) != 20
        lower, _, cap = chat.prepare_chat_model(model, max_output_tokens=256, request_timeout_seconds=20)
        assert getattr(lower, field) == cap == 256
        assert getattr(model, field) == 700
    finally:
        asyncio.run(close_model_clients(SimpleNamespace(llm=model)))
