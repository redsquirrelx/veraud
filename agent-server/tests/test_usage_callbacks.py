import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import BaseModel

from server.api.schemas import ExecutionConfig
from server.app import execution_service as execution_module
from server.app.agent_registry import AgentRegistry
from server.app.execution_service import AgentExecutionService
from server.app.pipeline_service import GenericPipelineService, GenericReportingHooks
from server.app.project_architecture_definition import ProjectArchitectureHooksAdapter
from server.app.usage_reporting import ReportingModel, gateway_progress
from server.infrastructure.callback.client import CallbackClient
from server.infrastructure.callback.schemas import (
    CallbackConfig,
    ExecutionOutcome,
    ExecutionProgress,
)
from server.infrastructure.tracing import NoOpTracingBackend
from server.runtimes.repository.model_runtime import ModelGateway
from server.runtimes.repository.schemas import ExecutionBudget


class Recorder:
    def __init__(self):
        self.events = []

    async def mark_running(self, execution_id):
        self.events.append(("running", execution_id, None))

    async def progress(self, execution_id, usage):
        self.events.append(("progress", execution_id, usage.model_copy()))

    async def complete(self, execution_id, outcome):
        self.events.append(("complete", execution_id, outcome))

    async def aclose(self):
        self.events.append(("close", None, None))


class Output(BaseModel):
    summary: str = "report"


class Model:
    settings = SimpleNamespace(name="test", max_tokens=1000)

    async def generate(self, prompt):
        return SimpleNamespace(content="response", usage_metadata={"input_tokens": 100, "output_tokens": 20})


def test_callback_client_sends_cumulative_camel_case_usage():
    requests = []

    def respond(request):
        import json
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"status": "Running"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = CallbackClient(CallbackConfig(backend_url="http://backend"), http)
            result = await client.progress(42, ExecutionProgress(input_tokens=100, output_tokens=20))
            assert result.acknowledged
            await client.complete(42, ExecutionOutcome(status="Completed", input_tokens=100, output_tokens=20))

    asyncio.run(run())
    assert requests[0] == ("/api/agent-executions/42/progress", {"inputTokens": 100, "outputTokens": 20, "estimatedTokens": 0})
    assert requests[1][1]["inputTokens"] == 100


@pytest.mark.parametrize("fail", [False, True])
def test_single_agent_reports_live_usage_and_final_counts(fail):
    sink = Recorder()

    class Agent:
        model = Model()
        input_schema = Output

        async def run(self, payload):
            await self.model.generate("first")
            assert sink.events[-1][0] == "progress"
            await self.model.generate("second")
            if fail:
                raise ValueError("agent failed")
            return Output()

    service = AgentExecutionService(callbacks_factory=lambda: sink, tracing_backend=NoOpTracingBackend())
    service.build_agent = lambda *args: (Agent(), 60)
    async def run():
        if fail:
            with pytest.raises(ValueError):
                await service.run("test", ExecutionConfig(), {}, execution_id=42)
        else:
            await service.run("test", ExecutionConfig(), {}, execution_id=42)

    asyncio.run(run())
    progress = [event[2] for event in sink.events if event[0] == "progress"]
    assert [(usage.input_tokens, usage.output_tokens) for usage in progress] == [(100, 20), (200, 40)]
    final = next(event[2] for event in sink.events if event[0] == "complete")
    assert (final.input_tokens, final.output_tokens) == (200, 40)
    assert final.status == ("Failed" if fail else "Completed")
    if fail:
        assert final.error_detail.agent_id == "test"
        assert final.error_detail.exception_type == "ValueError"
        assert final.error_detail.occurred_at is not None
        assert "agent failed" not in final.error_detail.message
    else:
        assert final.error_detail is None


def test_failed_direct_result_reports_incident_without_changing_delivery_semantics():
    sink = Recorder()

    class FailedOutput(BaseModel):
        status: str = "failed"

    class Agent:
        model = Model()
        input_schema = Output

        async def run(self, payload):
            await self.model.generate("first")
            return FailedOutput()

    service = AgentExecutionService(callbacks_factory=lambda: sink, tracing_backend=NoOpTracingBackend())
    service.build_agent = lambda *args: (Agent(), 60)
    asyncio.run(service.run("test", ExecutionConfig(), {}, execution_id=42))
    final = next(event[2] for event in sink.events if event[0] == "complete")
    assert final.status == "Completed"  # Successful delivery is not successful audit coverage.
    assert final.error_detail.agent_id == "test"
    assert final.error_detail.code == "execution_failed"
    assert (final.input_tokens, final.output_tokens) == (100, 20)


def test_direct_execution_closes_the_model_client_after_completion(monkeypatch):
    client = SimpleNamespace(aio=SimpleNamespace(aclose=AsyncMock()), close=Mock())
    model = Model()
    model.client = client

    class Agent:
        agent_type = "test"
        input_schema = Output
        output_schema = Output

        def __init__(self, settings, model):
            self.model = model
            self.settings = settings
            self.blackboard = None

        async def run(self, _payload):
            return Output()

    registry = AgentRegistry()
    registry.register("test", Agent)
    monkeypatch.setattr(execution_module, "build_model", lambda *_args: model)

    async def run():
        service = AgentExecutionService(
            registry=registry,
            callbacks_factory=lambda: None,
            tracing_backend=NoOpTracingBackend(),
        )
        await service.run(
            "test",
            ExecutionConfig(
                model={"provider": "openai", "name": "offline"},
                api_key="test-key",
            ),
            {},
        )

    asyncio.run(run())
    client.aio.aclose.assert_awaited_once_with()
    client.close.assert_called_once_with()


def test_missing_usage_is_estimated_and_callback_failure_does_not_fail_generation():
    class UnknownModel(Model):
        async def generate(self, prompt):
            return "response"

    class Offline(Recorder):
        async def progress(self, execution_id, usage):
            raise ConnectionError("backend unavailable")

    async def run():
        model = ReportingModel(UnknownModel(), Offline(), 42)
        assert await model.generate("input") == "response"
        assert model.usage.input_tokens is None
        assert model.usage.output_tokens is None
        assert model.usage.estimated_tokens == 4

    asyncio.run(run())


def test_gateway_usage_is_attributed_per_stage_including_architecture_revisions():
    sink = Recorder()
    stages = ["orientation", "architecture", "semantic_validation"]
    generic = GenericReportingHooks(sink, dict(zip(stages, [11, 12, 13])), stages)
    adapter = ProjectArchitectureHooksAdapter(generic)
    agents = {stage: SimpleNamespace(generate=ModelGateway(Model())) for stage in stages}
    adapter.bind_usage(agents, ExecutionBudget())

    async def run():
        for stage in stages:
            await adapter.on_stage_start(stage)
            await agents[stage].generate("prompt")
            await adapter.on_stage_result(stage, Output())
        assert not any(event[0] == "complete" and event[1] == 12 for event in sink.events)
        await agents["architecture"].generate("diagram")
        await adapter.on_stage_start("architecture")
        await agents["architecture"].generate("revision")
        await adapter.on_stage_result("architecture", Output(summary="revision"))
        await adapter.finish(SimpleNamespace(architecture=Output()))

    asyncio.run(run())
    completed = {event[1]: event[2] for event in sink.events if event[0] == "complete"}
    assert (completed[11].input_tokens, completed[13].input_tokens) == (100, 100)
    assert (completed[12].input_tokens, completed[12].output_tokens) == (300, 60)
    assert len([event for event in sink.events if event[:2] == ("running", 12)]) == 1


def test_retry_usage_keeps_unknown_attempts_separate_from_reported_counts():
    class RetryModel(Model):
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            if self.calls == 1:
                raise httpx.HTTPStatusError("busy", request=httpx.Request("POST", "http://model"), response=httpx.Response(429))
            return await super().generate(prompt)

    async def run():
        gateway = ModelGateway(RetryModel(), backoff=0)
        await gateway("prompt")
        usage = gateway_progress(gateway, ExecutionBudget())
        assert (usage.input_tokens, usage.output_tokens) == (100, 20)
        assert usage.estimated_tokens > 0
        assert gateway.usage_totals()["provider_attempts"] == 2

    asyncio.run(run())


def test_real_project_pipeline_reports_each_stage_and_closes_validation_last(tmp_path, monkeypatch):
    from server.app import project_architecture_definition as definition
    from server.project_analysis.project_architecture.smoke import (
        ArchitectureSmokeModel,
    )
    from server.project_analysis.project_semantic_validation.smoke import (
        SemanticValidationSmokeModel,
    )

    workspace = tmp_path / "workspace"
    repo = workspace / "repo"
    repo.mkdir(parents=True)
    (repo / "main.py").write_text("def main():\n    return 1\n")
    monkeypatch.setattr(definition, "resolve_workspace_root", lambda: workspace)
    monkeypatch.delenv("AGENT_SERVER_SMOKE_MODELS", raising=False)

    class SmokeWithUsage(ArchitectureSmokeModel):
        async def generate(self, prompt):
            response = await SemanticValidationSmokeModel().generate(prompt) if "\nVALIDATION_DATA\n" in prompt else await super().generate(prompt)
            return SimpleNamespace(content=response, usage_metadata={"input_tokens": 100, "output_tokens": 20})

    def create(settings, credentials):
        model = SmokeWithUsage()
        model.settings = settings
        return model

    monkeypatch.setattr(definition, "create_project_model", create)
    sink = Recorder()
    service = GenericPipelineService(callbacks_factory=lambda: sink, tracing_backend=NoOpTracingBackend())
    config = ExecutionConfig.model_validate({"model": {"provider": "OpenAI", "name": "test-model"}, "api_key": "test-key"})
    result = asyncio.run(service.run("project-architecture", {"root_path": str(repo)}, config, execution_ids={"orientation": 11, "architecture": 12, "semantic_validation": 13}))
    assert result["architecture"] is not None
    completed = {event[1]: event[2] for event in sink.events if event[0] == "complete"}
    assert set(completed) == {11, 12, 13}
    for execution_id, outcome in completed.items():
        updates = [event[2] for event in sink.events if event[:2] == ("progress", execution_id)]
        assert updates
        assert outcome.input_tokens == updates[-1].input_tokens
        assert outcome.output_tokens == updates[-1].output_tokens
    assert [event[1] for event in sink.events if event[0] == "complete"][-1] == 13
