"""Provider and execution configuration checks without external requests."""
import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from server.api import executions
from server.api.schemas import ExecutionConfig, ModelConfig
from server.app import execution_service
from server.config.schemas import ModelCredentials, ModelSettings
from server.infrastructure.llm import anthropic, gemini, openrouter
from server.main import app


def test_access_probe_uses_explicit_model_and_key_and_sanitizes_failures(monkeypatch):
    received = []
    denied = False

    class FakeModel:
        async def generate(self, message):
            if denied:
                raise RuntimeError("Provider error includes secret-key")
            return "OK"

    def build(settings, credentials):
        received.append((settings, credentials))
        return FakeModel()

    monkeypatch.setattr(executions, "build_model", build)
    with TestClient(app) as client:
        payload = {"model": {"provider": "OpenAI", "name": "model-A"}, "api_key": "secret-key"}
        response = client.post("/api/agents/verify-access", json=payload)
        assert response.status_code == 200
        assert response.json() == {"verified": True}
        assert received[0][0].provider == "OpenAI"
        assert received[0][0].name == "model-A"
        assert received[0][1].api_key == "secret-key"
        denied = True
        response = client.post("/api/agents/verify-access", json=payload)
        assert response.status_code == 422
        assert "secret-key" not in response.text
        response = client.post("/api/agents/verify-access", json={**payload, "model": "invalid"})
        assert response.status_code == 422
        assert "secret-key" not in response.text
        response = client.post("/api/agents/verify-access", json={"model": payload["model"]})
        assert response.status_code == 422


def test_openai_and_openrouter_use_their_own_endpoints(monkeypatch):
    received = []
    monkeypatch.setattr(openrouter, "ChatOpenAI", lambda **kwargs: received.append(kwargs))
    for provider in ("OpenAI", "OpenRouter"):
        openrouter.OpenRouterModel(ModelSettings(provider=provider, name="model", temperature=0.7, max_tokens=4096), ModelCredentials(api_key="key"))
    assert received[0]["base_url"] == "https://api.openai.com/v1"
    assert received[1]["base_url"] == "https://openrouter.ai/api/v1"
    assert received[0]["temperature"] == 0.7
    assert received[0]["max_tokens"] == 4096
    assert received[0]["api_key"] == "key"


def test_google_applies_generation_parameters(monkeypatch):
    received = []

    async def send_message(message):
        return SimpleNamespace(text="OK")

    def create(**kwargs):
        received.append(kwargs)
        return SimpleNamespace(send_message=send_message)

    monkeypatch.setattr(gemini.genai, "Client", lambda **kwargs: SimpleNamespace(aio=SimpleNamespace(chats=SimpleNamespace(create=create))))
    model = gemini.GeminiModel(ModelSettings(provider="Google", name="gemini-test", temperature=0, max_tokens=1234), ModelCredentials(api_key="key"))
    assert asyncio.run(model.generate("test")) == "OK"
    assert received[0]["model"] == "gemini-test"
    assert received[0]["config"].temperature == 0
    assert received[0]["config"].max_output_tokens == 1234


def test_anthropic_applies_saved_model_and_credentials(monkeypatch):
    received = []
    monkeypatch.setattr(anthropic, "ChatAnthropic", lambda **kwargs: received.append(kwargs))
    execution_service.build_model(ModelSettings(provider="Anthropic", name="claude-test", temperature=0.5, max_tokens=2048), ModelCredentials(api_key="anthropic-key"))
    assert received[0]["model"] == "claude-test"
    assert received[0]["api_key"] == "anthropic-key"
    assert received[0]["temperature"] == 0.5
    assert received[0]["max_tokens"] == 2048


def test_backend_overrides_are_used_in_agent_construction(monkeypatch):
    monkeypatch.setattr(execution_service.tracing, "setup", lambda: None)
    received = []
    monkeypatch.setattr(execution_service, "build_model", lambda settings, credentials: received.append((settings, credentials)) or SimpleNamespace(settings=settings))
    service = execution_service.AgentExecutionService()
    service.build_agent("dummy", ExecutionConfig(
        model=ModelConfig(provider="OpenAI", name="selected-model", temperature=0.8, max_tokens=4096), api_key="selected-key",
    ))
    assert received[0][0].name == "selected-model"
    assert received[0][0].temperature == 0.8
    assert received[0][0].max_tokens == 4096
    assert received[0][1].api_key == "selected-key"
