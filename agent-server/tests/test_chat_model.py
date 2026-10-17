from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from server.config.schemas import ModelCredentials, ModelSettings
from server.infrastructure.llm import chat
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
