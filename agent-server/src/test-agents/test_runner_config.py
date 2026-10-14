r"""Ejecutar desde agent-server (PowerShell):

    uv run pytest src/test-agents/test_runner_config.py -q

Verifica configuración YAML/.env e integración con LangSmithTracingBackend usando
archivos temporales y tracing simulado. No lee claves reales ni llama a servicios.
Para todas las pruebas offline: uv run pytest src/test-agents -q
"""

import asyncio
import importlib.util
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.config import dev_agents_config
from server.config.schemas import ModelSettings
from server.config.settings import TracingSettings


@pytest.fixture
def runner(monkeypatch, tmp_path):
    path = Path(__file__).with_name("run_architecture_boundary.py")
    spec = importlib.util.spec_from_file_location("boundary_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config_path = tmp_path / "dev-agents.yaml"
    config_path.write_text(
        "agents:\n  dummy:\n    model:\n      provider: google\n"
        "      name: configured-model\n      temperature: 0.7\n      max_tokens: 2048\n",
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_API_KEY=fixture-secret\nUNRELATED_SETTING=ignored\n", encoding="utf-8")
    monkeypatch.setattr(dev_agents_config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(module, "ENV_FILE", env_path)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    captured = {}

    def init(model, **kwargs):
        captured.update(model=model, **kwargs)
        return "fake-native-model"

    monkeypatch.setattr(module, "init_chat_model", init)
    return module, captured, env_path


def test_model_from_yaml_and_key_from_env_file(runner, monkeypatch, tmp_path):
    module, captured, _ = runner
    monkeypatch.chdir(tmp_path)
    model, settings = module.load_test_model()
    assert model == "fake-native-model"
    assert settings.name == "configured-model"
    assert captured == {"model": "configured-model", "model_provider": "google_genai",
                        "api_key": "fixture-secret", "temperature": 0.7,
                        "max_tokens": 2048, "max_retries": 0}


def test_environment_overrides_dotenv(runner, monkeypatch):
    module, captured, _ = runner
    monkeypatch.setenv("LLM_API_KEY", "environment-secret")
    module.load_test_model()
    assert captured["api_key"] == "environment-secret"


def test_missing_key_and_unknown_agent_fail_before_provider_init(runner):
    module, captured, env_path = runner
    env_path.write_text("UNRELATED_SETTING=ignored\n", encoding="utf-8")
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        module.load_test_model()
    with pytest.raises(ValueError, match="No agent configuration"):
        module.load_test_model("missing")
    assert captured == {}


@pytest.fixture
def audit_runner(runner, monkeypatch, tmp_path):
    from server.config import tracing

    module, _, _ = runner
    # Never read the developer's LangSmith credentials, even if configured locally.
    monkeypatch.setattr(tracing, "get_tracing_settings", lambda: TracingSettings(
        _env_file=None, langsmith_api_key="",
    ))
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "module.py").write_text("def example():\n    return 1\n", encoding="utf-8")
    active_span = ContextVar("test_active_span", default=None)
    calls = []

    class FakeAgent:
        def __init__(self, model, config):
            assert model == "fake-native-model"
            assert config.max_output_tokens == 2048

        async def run(self, tools, request):
            calls.append({"span": active_span.get(), "tools": tools, "request": request})
            return SimpleNamespace(model_dump=lambda **kwargs: {"audit": "completed"})

    monkeypatch.setattr(module, "ArchitectureBoundaryAgent", FakeAgent)
    settings = ModelSettings(provider="google", name="configured-model", temperature=0.7, max_tokens=2048)

    async def execute(**kwargs):
        await module.run_audit(
            SimpleNamespace(max_files=10), root, module.AuditRequest(), module.BoundaryConfig(),
            "fake-native-model", settings, **kwargs,
        )

    return execute, calls, active_span, tracing, module


def test_default_langsmith_backend_is_noop_without_key(audit_runner, monkeypatch, capsys):
    execute, calls, _, tracing, _ = audit_runner

    def unexpected_client(**kwargs):
        raise AssertionError("No LangSmith client should be created without a key")

    monkeypatch.setattr(tracing, "get_cached_client", unexpected_client)
    asyncio.run(execute())
    assert len(calls) == 1
    assert calls[0]["span"] is None
    assert '"audit": "completed"' in capsys.readouterr().out


def test_default_langsmith_backend_wraps_execution_and_safe_metadata(audit_runner, monkeypatch, capsys):
    execute, calls, active_span, tracing, _ = audit_runner
    client = object()
    spans = []
    monkeypatch.setattr(tracing, "setup", lambda: client)
    monkeypatch.setattr(tracing, "get_tracing_settings", lambda: TracingSettings(
        _env_file=None, langsmith_api_key="offline-tracing-key",
        langsmith_project="test-audits", langsmith_tags="offline,boundary",
    ))

    def traceable(**kwargs):
        spans.append(kwargs)

        def decorate(function):
            async def wrapped():
                token = active_span.set(kwargs["name"])
                try:
                    return await function()
                finally:
                    active_span.reset(token)

            return wrapped

        return decorate

    monkeypatch.setattr(tracing, "traceable", traceable)
    asyncio.run(execute())
    assert len(calls) == len(spans) == 1
    assert calls[0]["span"] == "architecture-boundary"
    span = spans[0]
    assert span["client"] is client
    assert span["project_name"] == "test-audits"
    assert span["tags"] == ["offline", "boundary"]
    assert span["metadata"] == {
        "agent_type": "architecture_boundary", "repository_id": "checkout",
        "commit": None, "snapshot_hash": calls[0]["tools"].context.input.snapshot_hash,
        "provider": "google", "model": "configured-model",
    }
    assert "key" not in str(span["metadata"])
    assert '"audit": "completed"' in capsys.readouterr().out


def test_runner_accepts_injected_tracing_backend(audit_runner):
    from server.app.tracing_port import TracingBackend

    execute, calls, _, _, _ = audit_runner
    recorded = []

    class Recorder(TracingBackend):
        async def wrap_stage(self, coro, *, name, **metadata):
            recorded.append((name, metadata))
            return await coro

    asyncio.run(execute(tracing_backend=Recorder()))
    assert len(calls) == len(recorded) == 1
    assert recorded[0][0] == "architecture-boundary"


def test_tracing_preserves_agent_failures(audit_runner, monkeypatch):
    execute, calls, _, _, module = audit_runner

    async def fail(self, tools, request):
        calls.append("failed")
        raise RuntimeError("audit-failed")

    monkeypatch.setattr(module.ArchitectureBoundaryAgent, "run", fail)
    with pytest.raises(RuntimeError, match="audit-failed"):
        asyncio.run(execute())
    assert calls == ["failed"]
