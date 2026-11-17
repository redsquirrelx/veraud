"""Production access must be explicit; local runners retain their dev resolver."""

import asyncio
import importlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from config.agents.model import ModelCredentials, ModelSettings
from server.api import verification_suite as suite_api
from server.api.verification_suite import VerificationSuiteRequest
from server.app.verification_model_configuration import VerificationModelConfiguration
from server.infrastructure.llm import chat_factory

CLIENTS = [
    ("finding_test_generation", "ProviderFindingLLMClient", "FindingTestConfig"),
    ("testability_probe", "ProviderProbeLLMClient", "TestabilityProbeConfig"),
]


@pytest.mark.parametrize("package,client_name,config_name", CLIENTS)
def test_explicit_access_never_reads_development_files(package, client_name, config_name, monkeypatch):
    module = importlib.import_module(f"server.agents.{package}.llm_client")
    config = getattr(importlib.import_module(f"server.agents.{package}.config"), config_name)()

    def forbidden(*args, **kwargs):
        pytest.fail("Production must never read dev-agents.yaml or .env")

    monkeypatch.setattr(module, "load_dev_agents_config", forbidden)
    monkeypatch.setattr(module, "RunnerCredentials", forbidden)
    seen = []
    model = SimpleNamespace()
    monkeypatch.setattr(module, "build_chat_model", lambda settings, credentials: seen.append((settings, credentials)) or model)
    monkeypatch.setattr(module, "model_pacer", lambda *args, **kwargs: None)
    transport = VerificationModelConfiguration.model_validate({
        "model": {"provider": "openai", "name": "production-model", "temperature": 0, "max_tokens": 24000},
        "api_key": "production-test-secret",
    })
    settings, credentials = transport.resolve(config)
    client = getattr(module, client_name)(config, settings=settings, credentials=credentials)
    assert client.model is model
    assert seen[0][0].name == "production-model"
    assert seen[0][0].temperature == 0
    assert seen[0][0].max_tokens == client.max_output_tokens == 24000
    assert seen[0][1].api_key == "production-test-secret"
    assert "production-test-secret" not in repr(transport)


@pytest.mark.parametrize("package,client_name,config_name", CLIENTS)
def test_runner_defaults_still_use_dummy_and_environment_key(package, client_name, config_name, monkeypatch):
    module = importlib.import_module(f"server.agents.{package}.llm_client")
    config = getattr(importlib.import_module(f"server.agents.{package}.config"), config_name)(provider_temperature_override=0)
    monkeypatch.setenv("LLM_API_KEY", "local-test-secret")
    settings = ModelSettings(provider="google", name="local-dummy-model", temperature=1, max_tokens=4000)
    monkeypatch.setattr(module, "load_dev_agents_config", lambda: {"dummy": (None, settings)})
    seen = []
    monkeypatch.setattr(module, "build_chat_model", lambda settings, credentials: seen.append((settings, credentials)) or SimpleNamespace())
    monkeypatch.setattr(module, "model_pacer", lambda *args, **kwargs: None)
    getattr(module, client_name)(config)
    assert seen[0][0].name == "local-dummy-model"
    assert seen[0][0].temperature == 0
    assert seen[0][1].api_key == "local-test-secret"
    assert settings.temperature == 1  # Do not mutate the trusted development base.


def test_generation_requires_configuration_but_execution_is_model_free():
    with pytest.raises(ValidationError, match="Configure the Verification Suite"):
        VerificationSuiteRequest(action="create")
    assert VerificationSuiteRequest(action="execute").config is None
    assert VerificationSuiteRequest(action="create", llm="none").config is None
    for body in ({"model": {}, "api_key": "key"},
                 {"model": {"provider": "google", "name": "model"}, "api_key": " "}):
        with pytest.raises(ValidationError, match="explicit provider, model and credential"):
            VerificationModelConfiguration.model_validate(body)


def test_probe_keeps_oracle_contract_in_system_role_and_accounts_for_usage(monkeypatch):
    from langchain_core.messages import HumanMessage, SystemMessage

    from server.agents.testability_probe import llm_client as module
    from server.agents.testability_probe.config import TestabilityProbeConfig

    seen = []

    class Model:
        async def ainvoke(self, messages):
            seen.extend(messages)
            return SimpleNamespace(content="corrected test", usage_metadata={"input_tokens": 5, "output_tokens": 2})

    class Pacer:
        async def acquire(self, estimate):
            return estimate

        def settle(self, reservation, spent):
            pass

    monkeypatch.setattr(module, "build_chat_model", lambda *args: Model())
    monkeypatch.setattr(module, "model_pacer", lambda *args, **kwargs: Pacer())
    client = module.ProviderProbeLLMClient(TestabilityProbeConfig(),
        settings=ModelSettings(provider="google", name="test-model", temperature=0, max_tokens=4000),
        credentials=ModelCredentials(api_key="test-key"))
    data = "Candidate comment: assert that the violation exists."
    assert asyncio.run(client.complete("repair", data)) == "corrected test"
    assert isinstance(seen[0], SystemMessage)
    assert "HEALTHY invariant" in seen[0].content
    assert isinstance(seen[1], HumanMessage)
    assert seen[1].content == data
    assert client.calls == 1 and client.used_tokens == 7


@pytest.mark.parametrize("package,client_name,runner_name", [
    ("finding_test_generation", "ProviderFindingLLMClient", "_run_finding_test_generation"),
    ("testability_probe", "ProviderProbeLLMClient", "_run_probe"),
])
def test_suite_composition_supplies_production_access_to_each_generator(package, client_name, runner_name, tmp_path, monkeypatch):
    module = importlib.import_module(f"server.agents.{package}.llm_client")
    agent_module = importlib.import_module(f"server.agents.{package}.agent")
    seen = []
    sentinel = object()

    def client(config, **kwargs):
        seen.append(kwargs)
        return sentinel

    class Agent:
        def __init__(self, config, llm_client):
            assert llm_client is sentinel
            assert not config.allow_local_unsafe_execution

        async def run(self, request):
            return "result"

    monkeypatch.setattr(module, client_name, client)
    if package == "finding_test_generation":
        monkeypatch.setattr(suite_api, "FindingTestGenerationAgent", Agent)
    else:
        monkeypatch.setattr(agent_module, "TestabilityProbeAgent", Agent)
    body = VerificationSuiteRequest(allow_execution=False, config=VerificationModelConfiguration.model_validate({
        "model": {"provider": "openai", "name": "suite-model", "temperature": 0, "max_tokens": 16000}, "api_key": "secret",
    }))
    result = asyncio.run(getattr(suite_api, runner_name)("run", {"auditId": 1}, [], str(tmp_path), tmp_path, body))
    assert result == "result"
    assert seen[0]["settings"].name == "suite-model"
    assert seen[0]["settings"].max_tokens == 16000
    assert seen[0]["credentials"].api_key == "secret"
    assert "secret" not in "".join(path.read_text(encoding="utf-8") for path in tmp_path.glob("*.json"))


@pytest.mark.parametrize("provider,expected,url", [
    ("google", "google_genai", None), ("OpenAI", "openai", None),
    ("openrouter", "openai", "https://openrouter.ai/api/v1"),
    ("groq", "openai", "https://api.groq.com/openai/v1"), ("anthropic", "anthropic", None),
])
def test_provider_mapping_keeps_configured_parameters(provider, expected, url, monkeypatch):
    seen = []
    monkeypatch.setattr(chat_factory, "init_chat_model", lambda name, **kwargs: seen.append((name, kwargs)))
    chat_factory.build_chat_model(ModelSettings(provider=provider, name="model", temperature=0, max_tokens=24000),
                                  ModelCredentials(api_key="key"))
    name, options = seen[0]
    assert name == "model" and options["model_provider"] == expected
    assert options.get("base_url") == url
    assert options["api_key"] == "key" and options["temperature"] == 0 and options["max_tokens"] == 24000
