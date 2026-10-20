import asyncio
import base64
import io
import subprocess
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from server.api.schemas import ExecutionConfig
from server.app import audit_service, quality_audit_definition
from server.app.audit_models import MAINTAINABILITY_AGENT_TYPES
from server.app.audit_service import AuditService
from server.app.callback_port import CallbackSink
from server.app.execution_service import InvalidConfigError
from server.app.pipeline_service import GenericPipelineService
from server.app.tracing_port import NoOpTracingBackend
from server.blackboard.impls.memory import MemoryBlackboard
from server.blackboard.models import Assessment
from server.infrastructure.callback.schemas import CallbackResult
from server.services.audit_report_snapshot import (
    BlackboardSnapshot,
    report_from_snapshot,
)

pytest_plugins = ["test_audits"]


@pytest.mark.parametrize("explicit_models", [False, True])
def test_pipeline_preserves_partial_audit_and_returns_the_existing_report_and_docx(audit_environment, monkeypatch, explicit_models):
    root = audit_environment.root
    for args in (["init"], ["add", "."], ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: root.parent)
    # Uvicorn reload workers on Windows may not implement async subprocesses.
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=NotImplementedError))

    class Manager:
        def __init__(self, model, limits, *, blackboard, audit_identity, tracing_backend):
            self.board, self.identity = blackboard, audit_identity

        async def run(self, tools, request):
            assert set(self.agent_models) == (set(MAINTAINABILITY_AGENT_TYPES) if explicit_models else set())
            self.board.publish_assessment(Assessment(
                agent_id="maintainability_manager", run_id=self.identity.run_id,
                invocation_id=self.identity.invocation_id, quality_attribute="maintainability",
                repository_id=tools.accessible_snapshot.repository.name,
                snapshot_hash=tools.context.input.snapshot_hash, objective=request.objective,
                status="partial", termination_reason="round_limit", limitations=("Cobertura pendiente",),
            ))
            return SimpleNamespace(status="partial")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    board = MemoryBlackboard()

    async def execute():
        service = GenericPipelineService(tracing_backend=NoOpTracingBackend())
        return await service.run("quality-audit", {
            "root_path": str(root), "commit_hash": commit, "attributes": ["maintainability"],
        }, ExecutionConfig(), stage_configs={name: ExecutionConfig(
            model={"provider": "openai", "name": "common-model"}, api_key="private-key")
            for name in MAINTAINABILITY_AGENT_TYPES} if explicit_models else None, blackboard=board)

    payload = asyncio.run(execute())["audit"]
    assert payload["status"] == "partial"
    assert payload["report"]["schema_version"] == "1.0"
    assert payload["report"]["identification"]["status"] == "partial"
    assert payload["blackboard"]["assessments"]
    assert board.query_assessments(payload["run_id"])
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload["docx_base64"]))) as document:
        assert b"Cobertura pendiente" in document.read("word/document.xml")
    assert "private-key" not in str(payload)
    audit_environment.async_client.aclose.assert_awaited_once()
    audit_environment.factory.assert_called_once()  # Identical selections share a client, not nine pools.


class _RecordingSink(CallbackSink):
    """Captures lifecycle callbacks so their order can be asserted."""

    def __init__(self):
        self.running: list[tuple[int, str | None]] = []
        self.invocations = []

    async def invocation(self, execution_id, receipt):
        self.invocations.append((execution_id, receipt.model_dump(mode="json")))
        return CallbackResult(acknowledged=True)

    async def mark_running(self, execution_id, run_id=None):
        self.running.append((execution_id, run_id))
        return CallbackResult(acknowledged=True)

    async def complete(self, execution_id, outcome):
        return CallbackResult(acknowledged=True)

    async def progress(self, execution_id, usage):
        return CallbackResult(acknowledged=True)

    async def aclose(self):
        return None


def _committed_checkout(root):
    for args in (["init"], ["add", "."], ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def test_security_pipeline_resolves_its_own_stage_and_returns_portable_artifacts(audit_environment, monkeypatch):
    commit = _committed_checkout(audit_environment.root)
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: audit_environment.root.parent)
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock()
    sink = _RecordingSink()

    async def execute():
        service = GenericPipelineService(callbacks_factory=lambda: sink, tracing_backend=NoOpTracingBackend())
        return await service.run("quality-audit", {
            "root_path": str(audit_environment.root), "commit_hash": commit, "attributes": ["security"],
        }, ExecutionConfig(), stage_configs={"security": ExecutionConfig(
            model={"provider": "openai", "name": "security-model"}, api_key="security-key")},
            execution_ids={"security": 42})

    payload = asyncio.run(execute())["audit"]
    assert payload["attributes"] == ["security"]
    assert payload["status"] == "completed"
    assert payload["report"]["identification"]["status"] == "completed"
    assert payload["blackboard"]["execution_issues"] == []
    assert payload["blackboard"]["assessments"][0]["agent_id"] == "security"
    assert sink.running == [(42, None), (42, payload["run_id"])]
    assert payload["docx_base64"]
    assert "security-key" not in str(payload)


def test_joint_pipeline_applies_common_and_security_overrides_to_the_real_toolsets(audit_environment, monkeypatch):
    root = audit_environment.root
    (root / "extra.py").write_text("first = 1\nsecond = 2\n", encoding="utf-8")
    commit = _committed_checkout(root)
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: root.parent)
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    captured = {}

    class Manager:
        def __init__(self, selected_model, limits, *, blackboard, audit_identity, tracing_backend):
            captured["limits"] = limits
            self.board, self.identity = blackboard, audit_identity

        async def run(self, tools, request):
            captured["audit_tokens"] = tools.token_budget.root.limit
            self.board.publish_assessment(Assessment(agent_id="maintainability_manager", run_id=self.identity.run_id,
                invocation_id=self.identity.invocation_id, quality_attribute="maintainability",
                repository_id=tools.context.snapshot.repository.name, snapshot_hash=tools.context.input.snapshot_hash,
                objective=request.objective, status="complete", termination_reason="sufficient_coverage"))
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)

    async def execute():
        return (await GenericPipelineService(tracing_backend=NoOpTracingBackend()).run("quality-audit", {
            "root_path": str(root), "commit_hash": commit, "attributes": ["maintainability", "security"],
            "agent_defaults": {"max_context_characters": 40000, "max_total_tokens": 60000,
                "max_model_calls": 8, "max_tool_calls": 8},
            "security_config": {"max_tool_calls": 1, "max_source_lines": 1, "max_total_tokens": 2000,
                "max_retrieved_characters": 1},
            "audit_budget": {"max_total_tokens": 50000},
        }, ExecutionConfig()))["audit"]

    payload = asyncio.run(execute())
    assert payload["status"] == "partial"
    assert captured["limits"].max_context_characters == 40000
    assert captured["limits"].invocation_limits.invocation_limits.max_model_calls == 8
    assert captured["limits"].invocation_limits.invocation_limits.max_tool_calls == 8
    assert captured["audit_tokens"] == 50000
    security = next(item for item in payload["blackboard"]["assessments"] if item["agent_id"] == "security")
    analysis = security["details"]["security_analysis"]
    assert analysis["effective_config"]["max_tool_calls"] == 1
    assert analysis["effective_config"]["max_model_calls"] == 8
    assert analysis["effective_config"]["max_total_tokens"] == 2000
    assert analysis["audit_token_limit"] == 50000
    assert security["consumption"]["tool_calls"] == 1
    assert "security_retrieval_limit" in analysis["incomplete_reasons"]
    assert analysis["read_errors"][0]["code"] == "content_budget_exhausted"
    assert analysis["read_errors"][0]["remaining_retrieved_characters"] == 1


@pytest.mark.parametrize("failed_attribute", [None, "maintainability", "security", "security_timeout", "shared_token_limit"])
def test_joint_audit_shares_snapshot_run_and_report_and_isolates_failures(audit_environment, monkeypatch, failed_attribute):
    root = audit_environment.root
    (root / "main.py").write_text('password = "example-secret"\n', encoding="utf-8")
    commit = _committed_checkout(root)
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: root.parent)
    captured = {}
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value='{"patch_code": "safe()", "explanation": "Revisar contexto"}')
    if failed_attribute == "security_timeout":
        policy = audit_service.SecurityAuditConfig(timeout_seconds=0.05)
        monkeypatch.setattr(audit_service, "SecurityAuditConfig", lambda: policy)
        async def blocked(prompt, **kwargs):
            await asyncio.Event().wait()

        model.ainvoke = blocked
    original_security = audit_service.run_security_audit

    async def security(tools, request, limits, selected_model, board, identity):
        captured["security"] = (tools.context.snapshot, tools.token_budget.root, identity)
        if failed_attribute == "security":
            raise RuntimeError("private-provider-payload")
        return await original_security(tools, request, limits, selected_model, board, identity)

    class Manager:
        def __init__(self, selected_model, limits, *, blackboard, audit_identity, tracing_backend):
            self.board, self.identity = blackboard, audit_identity

        async def run(self, tools, request):
            captured["maintainability"] = (tools.context.snapshot, tools.token_budget.root, self.identity)
            assert set(self.agent_models) == set(MAINTAINABILITY_AGENT_TYPES)
            if failed_attribute == "maintainability":
                raise RuntimeError("private-provider-payload")
            if failed_attribute == "shared_token_limit":
                assert tools.token_budget.reserve(tools.token_budget.remaining) is not None
            self.board.publish_assessment(Assessment(agent_id="maintainability_manager", run_id=self.identity.run_id,
                invocation_id=self.identity.invocation_id, quality_attribute="maintainability",
                repository_id=tools.context.snapshot.repository.name, snapshot_hash=tools.context.input.snapshot_hash,
                objective=request.objective, status="complete", termination_reason="sufficient_coverage"))
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    monkeypatch.setattr(audit_service, "run_security_audit", security)
    analysis = audit_service.RepositoryAnalysisService()
    analyze = AsyncMock(wraps=analysis.analyze)
    monkeypatch.setattr(audit_service, "RepositoryAnalysisService", lambda: SimpleNamespace(analyze=analyze))
    sink = _RecordingSink()

    async def execute():
        service = GenericPipelineService(callbacks_factory=lambda: sink, tracing_backend=NoOpTracingBackend())
        payload = (await service.run("quality-audit", {
            "root_path": str(root), "commit_hash": commit, "attributes": ["security", "maintainability"],
        }, ExecutionConfig(), stage_configs={name: ExecutionConfig(
            model={"provider": "openai", "name": name}, api_key=name + "-key")
            for name in [*MAINTAINABILITY_AGENT_TYPES, "security"]}, execution_ids={"maintainability_manager": 42}))["audit"]
        restored = await report_from_snapshot(BlackboardSnapshot.model_validate(payload["blackboard"]))
        return payload, restored

    payload, restored = asyncio.run(execute())
    assert payload["status"] == ("completed" if failed_attribute is None else "partial")
    if failed_attribute is None:
        assert payload["blackboard"]["execution_issues"] == []
        assert restored.identification.status == "partial"  # Quality claims remain inconclusive.
    assert {item["quality_attribute"] for item in payload["blackboard"]["assessments"]} == {"maintainability", "security"}
    assert {item["run_id"] for item in payload["blackboard"]["assessments"]} == {payload["run_id"]}
    assert captured["maintainability"][0] is captured["security"][0]
    assert captured["maintainability"][1] is captured["security"][1]
    assert captured["maintainability"][2].invocation_id != captured["security"][2].invocation_id
    analyze.assert_awaited_once()
    assert sink.running == [(42, None), (42, payload["run_id"])]
    assert {item.id for item in restored.quality_results.attributes if item.status != "not_evaluated"} >= {"maintainability", "security"}
    assert restored.identification.audit_id == payload["run_id"]
    assert "La ejecución principal aún no ha publicado una evaluación final." not in str(restored)
    assert "private-provider-payload" not in str(payload)
    if failed_attribute == "shared_token_limit":
        model.ainvoke.assert_not_awaited()
        assert payload["blackboard"]["findings"]
    if failed_attribute == "security_timeout":
        assert any(item["quality_attribute"] == "security" and item["status"] == "failed"
            for item in payload["blackboard"]["assessments"])
        assert any(item["quality_attribute"] == "maintainability" and item["status"] == "complete"
            for item in payload["blackboard"]["assessments"])
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload["docx_base64"]))) as document:
        xml = document.read("word/document.xml").decode()
        assert "Mantenibilidad" in xml and "Seguridad" in xml


def test_pipeline_reports_the_run_id_before_the_audit_finishes(audit_environment, monkeypatch):
    """The backend learns the run id while the audit still runs, so its board page can follow it."""
    commit = _committed_checkout(audit_environment.root)
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: audit_environment.root.parent)
    board = MemoryBlackboard()
    service = AuditService(board)
    sink = _RecordingSink()
    seen = {}

    class Manager:
        def __init__(self, model, limits, *, blackboard, audit_identity, tracing_backend):
            self.run_id = audit_identity.run_id
            self.invocation_id = audit_identity.invocation_id

        async def run(self, tools, request):
            seen["run_id"] = self.run_id
            seen["state"] = service.get(self.run_id).status
            seen["snapshot"] = service.snapshot(self.run_id)
            from server.runtimes.invocation_reporting import observe_invocation

            async def child():
                assert service.get(self.run_id).status == "running"
                receipts = [receipt for execution_id, receipt in sink.invocations if execution_id == 21]
                assert len(receipts) == 2
                assert receipts[0]["invocation_id"] == self.invocation_id
                assert receipts[1]["parent_invocation_id"] == self.invocation_id
                assert all(receipt["status"] == "running" for receipt in receipts)
                return SimpleNamespace(status="partial")

            await observe_invocation(child(), agent_id="modularity", invocation_id="coordinator-live", run_id=self.run_id)
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)

    async def execute():
        pipeline = GenericPipelineService(tracing_backend=NoOpTracingBackend(), callbacks_factory=lambda: sink)
        return await pipeline.run("quality-audit", {"root_path": str(audit_environment.root),
            "commit_hash": commit, "attributes": ["maintainability"]}, ExecutionConfig(),
            execution_ids={"maintainability_manager": 21}, blackboard=board, audit_service=service)

    payload = asyncio.run(execute())["audit"]
    assert sink.running == [(21, None), (21, seen["run_id"])]
    assert seen["run_id"] == payload["run_id"]
    assert seen["state"] == "running"
    assert seen["snapshot"].findings == []
    assert service.get(payload["run_id"]).status == "completed"
    assert [receipt["status"] for _, receipt in sink.invocations] == ["running", "running", "partial", "completed"]


def test_failed_pipeline_cancels_its_audit_and_leaves_the_service_open(audit_environment, monkeypatch):
    commit = _committed_checkout(audit_environment.root)
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: audit_environment.root.parent)
    board = MemoryBlackboard()
    service = AuditService(board)
    sink = _RecordingSink()

    class Manager:
        def __init__(self, model, limits, *, blackboard, audit_identity, tracing_backend):
            self.run_id = audit_identity.run_id

        async def run(self, tools, request):
            await asyncio.Event().wait()

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)

    async def execute():
        pipeline = GenericPipelineService(tracing_backend=NoOpTracingBackend(), callbacks_factory=lambda: sink)
        return await pipeline.run("quality-audit", {"root_path": str(audit_environment.root),
            "commit_hash": commit, "attributes": ["maintainability"]}, ExecutionConfig(),
            execution_ids={"maintainability_manager": 21}, timeout_seconds=1, blackboard=board,
            audit_service=service)

    with pytest.raises(TimeoutError):
        asyncio.run(execute())
    run_id = sink.running[-1][1]
    assert run_id is not None and service.get(run_id).status == "cancelled"
    assert service._closing is False


def test_direct_audit_rejects_incomplete_agent_models_before_scheduling(audit_environment):
    from fastapi.testclient import TestClient

    from server.main import app

    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "agent_configs": {"maintainability_manager": {"model": {"provider": "openai", "name": "model"}, "api_key": "private-key"}}})
        assert response.status_code == 422
        assert "private-key" not in response.text
        assert not app.state.audit_service._tasks
    audit_environment.factory.assert_not_called()


def test_direct_audit_resolves_distinct_models_and_closes_all_clients(audit_environment, monkeypatch):
    from fastapi.testclient import TestClient

    from server.config.schemas import ModelCredentials, ModelSettings
    from server.main import app

    clients = {}

    def resolve(agent_type, config):
        return (ModelSettings(provider=config.model.provider, name=config.model.name,
            temperature=0.2, max_tokens=1000), ModelCredentials(api_key=config.api_key), 1200)

    def build(settings, credentials):
        model = SimpleNamespace(name=settings.name, key=credentials.api_key,
            client=SimpleNamespace(close=Mock()), async_client=SimpleNamespace(aclose=AsyncMock()))
        clients[settings.name] = model
        return model

    class Manager:
        def __init__(self, model, *args, **kwargs):
            assert model.name == "model-maintainability_manager"

        async def run(self, tools, request):
            assert {key: model.name for key, model in self.agent_models.items()} == {
                name: f"model-{name}" for name in MAINTAINABILITY_AGENT_TYPES}
            assert all(model.key == f"secret-{name}" for name, model in self.agent_models.items())
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "get_execution_service", lambda: SimpleNamespace(resolve_model_settings=resolve))
    monkeypatch.setattr(audit_service, "build_chat_model", build)
    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "agent_configs": {name: {"model": {"provider": "openai", "name": f"model-{name}"},
                "api_key": f"secret-{name}"} for name in MAINTAINABILITY_AGENT_TYPES}})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}")
        assert snapshot.json()["status"] == "completed"
        assert "secret-" not in snapshot.text
    assert len(clients) == len(MAINTAINABILITY_AGENT_TYPES)
    for model in clients.values():
        model.async_client.aclose.assert_awaited_once()
        model.client.close.assert_called_once()


@pytest.mark.parametrize("attributes", [[], ["unsupported"], ["maintainability", "security", "security"], ["maintainability", "maintainability"]])
def test_unimplemented_or_duplicate_attributes_are_rejected(attributes):
    with pytest.raises(InvalidConfigError):
        quality_audit_definition.parse_input({"root_path": "checkout", "commit_hash": "a" * 40, "attributes": attributes})


def test_changed_revision_is_rejected_before_spending_model_calls(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: tmp_path)
    factory = AsyncMock()
    monkeypatch.setattr(quality_audit_definition, "AuditService", factory)
    parsed = quality_audit_definition.parse_input({"root_path": str(root), "commit_hash": "a" * 40, "attributes": ["maintainability"]})
    with pytest.raises(InvalidConfigError, match="revision"):
        asyncio.run(quality_audit_definition.QualityAuditRunner(ExecutionConfig()).run(parsed, None))
    factory.assert_not_called()


@pytest.mark.parametrize("failure, message", [
    (subprocess.TimeoutExpired("git", 5), "timed out"),
    (FileNotFoundError("git"), "could not start"),
])
def test_git_verification_failure_is_controlled_before_audit_start(tmp_path, monkeypatch, failure, message):
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(quality_audit_definition.subprocess, "run", Mock(side_effect=failure))
    factory = Mock()
    monkeypatch.setattr(quality_audit_definition, "AuditService", factory)
    parsed = quality_audit_definition.parse_input({"root_path": str(root), "commit_hash": "a" * 40,
        "attributes": ["maintainability"]})
    with pytest.raises(InvalidConfigError, match=message):
        asyncio.run(quality_audit_definition.QualityAuditRunner(ExecutionConfig()).run(parsed, None))
    factory.assert_not_called()
