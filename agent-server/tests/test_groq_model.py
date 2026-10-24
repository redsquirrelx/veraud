import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from server.api.schemas import ExecutionConfig, ModelConfig
from server.app import execution_service
from server.app.execution_service import (
    AgentExecutionService,
    InvalidConfigError,
    build_model,
)
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings
from server.infrastructure.llm import groq
from server.infrastructure.llm.groq import GroqModel


def _settings(provider="groq", name="groq-test-model"):
    return ModelSettings(
        provider=provider, name=name, temperature=0.2, max_tokens=1000,
    )


def test_groq_client_settings_and_async_generation(monkeypatch):
    response = Mock(content="model answer")
    client = Mock(ainvoke=AsyncMock(return_value=response))
    constructor = Mock(return_value=client)
    monkeypatch.setattr(groq, "ChatOpenAI", constructor)

    model = build_model(_settings(provider="Groq"), ModelCredentials(api_key="test-key"))

    assert isinstance(model, GroqModel)
    constructor.assert_called_once_with(
        model="groq-test-model", temperature=0.2, max_tokens=1000,
        api_key="test-key", base_url="https://api.groq.com/openai/v1", max_retries=0,
    )
    assert asyncio.run(model.generate("prompt")) is response
    client.ainvoke.assert_awaited_once_with("prompt")


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(execution_service.tracing, "setup", lambda: None)
    monkeypatch.setattr(AgentExecutionService, "_server_api_key", staticmethod(lambda: "server-key"))
    service = AgentExecutionService()
    # Tests must not depend on the developer's local provider selection.
    service._base_config["dummy"] = (
        AgentSettings(agent_id="dummy", timeout_seconds=180),
        _settings(provider="gemini", name="gemini-test-model"),
    )
    return service


def test_switch_to_groq_requires_explicit_model(service):
    with pytest.raises(InvalidConfigError, match="model.name is required"):
        service.build_agent("dummy", ExecutionConfig(model=ModelConfig(provider="groq")))


def test_request_overrides_reach_groq_client(service, monkeypatch):
    constructor = Mock()
    monkeypatch.setattr(groq, "ChatOpenAI", constructor)
    agent, timeout = service.build_agent("dummy", ExecutionConfig(
        model=ModelConfig(provider="groq", name="groq-test-model", temperature=0.3, max_tokens=2000),
        api_key="request-key", timeout_seconds=45,
    ))

    assert isinstance(agent.model, GroqModel)
    assert timeout == 45
    constructor.assert_called_once_with(
        model="groq-test-model", temperature=0.3, max_tokens=2000,
        api_key="request-key", base_url="https://api.groq.com/openai/v1", max_retries=0,
    )


def test_yaml_groq_defaults_and_server_key(service, monkeypatch):
    service._base_config["dummy"] = (
        AgentSettings(agent_id="dummy", timeout_seconds=120), _settings(),
    )
    constructor = Mock()
    monkeypatch.setattr(groq, "ChatOpenAI", constructor)

    agent, timeout = service.build_agent("dummy", ExecutionConfig())

    assert isinstance(agent.model, GroqModel)
    assert timeout == 120
    assert constructor.call_args.kwargs["model"] == "groq-test-model"
    assert constructor.call_args.kwargs["api_key"] == "server-key"


def test_unknown_provider_still_rejected():
    with pytest.raises(InvalidConfigError, match="Unsupported model provider"):
        build_model(_settings(provider="unknown"), ModelCredentials(api_key="test-key"))
