import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from server.app import audit_service
from server.app.audit_service import AuditService
from server.app.execution_service import InvalidConfigError
from server.blackboard.impls.memory import MemoryBlackboard
from server.blackboard.models import Assessment, Evidence, Finding
from server.config.schemas import ModelCredentials, ModelSettings
from server.infrastructure.tracing import NoOpTracingBackend
from server.main import app


def test_http_cancellation_retains_evidence_and_does_not_cancel_sibling(audit_environment, monkeypatch):
    entered = asyncio.Event()
    runs = []

    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, tools, request):
            runs.append(tools)
            entered.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    with TestClient(app) as client:
        first = client.post("/api/audits", json={"repository_path": str(audit_environment.root)}).json()
        client.portal.call(entered.wait)
        entered.clear()
        second = client.post("/api/audits", json={"repository_path": str(audit_environment.root)}).json()
        client.portal.call(entered.wait)
        before = client.get(f"/api/audits/{first['run_id']}").json()["evidence"]
        response = client.post(f"/api/audits/{first['run_id']}/cancel")
        assert response.status_code == 202
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["location"] == f"/api/audits/{first['run_id']}"
        assert response.json()["status"] == "cancelled"
        assert client.get(f"/api/audits/{second['run_id']}").json()["status"] == "running"
        after = client.get(f"/api/audits/{first['run_id']}").json()["evidence"]
        assert before and all(item in after for item in before)
        assert client.post(f"/api/audits/{first['run_id']}/cancel").json()["status"] == "cancelled"
        assert client.post("/api/audits/missing/cancel").status_code == 404


def test_cancellation_before_first_task_turn_prevents_repository_and_model_work(audit_environment, monkeypatch):
    from server.agents.maintainability.manager import MaintainabilityRequest
    from server.app.execution_config import ExecutionConfig

    analyze = AsyncMock()
    monkeypatch.setattr(audit_service, "RepositoryAnalysisService", lambda: SimpleNamespace(analyze=analyze))

    async def execute():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), MaintainabilityRequest(), ExecutionConfig(), "offline")
        await service.cancel(state.run_id)
        assert service.get(state.run_id).status == "cancelled"
        assert not service._tasks and not service._cancellations
        analyze.assert_not_awaited()
        audit_environment.factory.assert_not_called()
        await service.aclose()

    asyncio.run(execute())


def test_late_work_stays_cancelling_and_cannot_start_new_stages(audit_environment, monkeypatch):
    from server.agents.maintainability.manager import (
        MaintainabilityConfig,
        MaintainabilityRequest,
    )
    from server.app.execution_config import ExecutionConfig

    limits = MaintainabilityConfig(cancellation_grace_seconds=0.01)
    monkeypatch.setattr(audit_service, "MaintainabilityConfig", lambda: limits)
    entered, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    attempts = []

    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, tools, request):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopping.set()
                await release.wait()  # Simulate a provider taking time to stop.
                with tools.timing.stage("must_not_start"):
                    attempts.append("started")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)

    async def execute():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), MaintainabilityRequest(), ExecutionConfig(), "offline")
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await service.cancel(state.run_id)
            assert stopping.is_set()
            assert service.get(state.run_id).status == "cancelling"
            await service.cancel(state.run_id)  # Must not cancel late cleanup a second time.
            assert service.get(state.run_id).status == "cancelling"
            assert any(item.status == "cancellation_pending" for item in service.snapshot(state.run_id).activity)
            release.set()
            for _ in range(100):
                if service.get(state.run_id).status == "cancelled":
                    break
                await asyncio.sleep(0)
            assert service.get(state.run_id).status == "cancelled"
            assert not attempts
            assert service.snapshot(state.run_id).evidence
        finally:
            release.set()
            await service.aclose()

    asyncio.run(execute())


@pytest.fixture
def audit_environment(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "main.py").write_text("def entry():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(audit_service, "resolve_workspace_root", lambda: tmp_path)
    resolver = Mock(return_value=(ModelSettings(provider="openai", name="offline", temperature=0.2, max_tokens=1000),
        ModelCredentials(api_key="private-key"), 1200))
    monkeypatch.setattr(audit_service, "resolve_model_settings", resolver)
    client = SimpleNamespace(close=Mock())
    async_client = SimpleNamespace(aclose=AsyncMock())
    model = SimpleNamespace(bind_tools=lambda tools: model, client=client, async_client=async_client)
    factory = Mock(return_value=model)
    monkeypatch.setattr(audit_service, "build_chat_model", factory)
    monkeypatch.setattr(audit_service, "LangSmithTracingBackend", NoOpTracingBackend)
    return SimpleNamespace(root=root, resolver=resolver, model=model, factory=factory,
        client=client, async_client=async_client)


def test_http_starts_without_waiting_and_manager_uses_the_server_blackboard(audit_environment, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    captured = {}

    class Manager:
        def __init__(self, model, limits, *, blackboard, audit_identity, tracing_backend):
            captured.update(board=blackboard, identity=audit_identity, limits=limits)

        async def run(self, tools, request):
            captured.update(tools=tools, request=request)
            entered.set()
            await release.wait()
            identity = captured["identity"]
            captured["board"].publish_assessment(Assessment(
                agent_id="maintainability_manager", run_id=identity.run_id, invocation_id=identity.invocation_id,
                repository_id=tools.accessible_snapshot.repository.name,
                snapshot_hash=tools.context.input.snapshot_hash, objective=request.objective,
                status="complete", termination_reason="sufficient_coverage",
            ))
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "request": {"objective": "Inspect maintainability"}})
        assert response.status_code == 202
        state = response.json()
        run_id = state["run_id"]
        assert state["status"] == "queued"
        assert response.headers["location"] == f"/api/audits/{run_id}"
        assert state["view_url"] == f"/blackboard?run_id={run_id}"
        client.portal.call(entered.wait)
        assert client.get(response.headers["location"]).json()["status"] == "running"
        assert captured["board"] is app.state.blackboard
        assert captured["identity"].run_id == run_id
        assert captured["identity"].invocation_id == state["invocation_id"]
        assert captured["tools"].context.input.budget.max_elapsed_seconds == captured["limits"].timeout_seconds
        task = app.state.audit_service._tasks[run_id]

        async def finish():
            release.set()
            await task

        client.portal.call(finish)
        assert client.get(response.headers["location"]).json()["status"] == "completed"
        assert len(app.state.blackboard.query_assessments(run_id, state["invocation_id"])) == 1
        assert "private-key" not in client.get(response.headers["location"]).text
    audit_environment.client.close.assert_called_once()
    audit_environment.async_client.aclose.assert_awaited_once()


def test_absolute_audit_deadline_expires_even_while_all_work_is_waiting_for_quota(audit_environment, monkeypatch):
    from server.agents.maintainability.manager import (
        MaintainabilityConfig,
        MaintainabilityRequest,
    )
    from server.api.schemas import ExecutionConfig

    snapshot = audit_service.RepositoryAnalysisService().analyze_sync(audit_environment.root)
    monkeypatch.setattr(audit_service, "RepositoryAnalysisService", lambda: SimpleNamespace(analyze=AsyncMock(return_value=snapshot)))
    limits = MaintainabilityConfig(max_wall_time_seconds=0.15, cancellation_grace_seconds=0.01)
    monkeypatch.setattr(audit_service, "MaintainabilityConfig", lambda: limits)
    entered = asyncio.Event()

    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, tools, request):
            with tools.timing.quota_wait(reason="rpm", seconds=60):
                entered.set()
                await asyncio.Event().wait()

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)

    async def execute():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), MaintainabilityRequest(), ExecutionConfig(), "offline")
        task = service._tasks[state.run_id]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            current = service.snapshot(state.run_id)
            assert current.activity[0].stage == "maintainability_audit"
            assert current.waiting[0].reason == "rpm"
            assert 0 < current.wall_seconds_remaining <= 0.15
            assert current.active_seconds_remaining > 1000
            done, _ = await asyncio.wait({task}, timeout=0.6)
            assert done, "Quota admission bypassed the audit's absolute deadline"
            assert service.get(state.run_id).status == "failed"
            assert service.get(state.run_id).error == "The execution exceeded its allowed time."
            assert service.snapshot(state.run_id).evidence  # Initial audit context survives timeout.
        finally:
            await service.aclose()

    asyncio.run(execute())


@pytest.mark.parametrize("outcome, expected", [("partial", "partial"), ("failed", "failed"), ("error", "failed")])
def test_terminal_results_and_errors_are_recorded_and_clients_closed(audit_environment, monkeypatch, outcome, expected):
    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, tools, request):
            if outcome == "error":
                raise RuntimeError("private-key must not appear")
            return SimpleNamespace(status=outcome)

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)

    async def execute():
        from server.agents.maintainability.manager import MaintainabilityRequest
        from server.api.schemas import ExecutionConfig

        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), MaintainabilityRequest(), ExecutionConfig(), "dummy")
        await service._tasks[state.run_id]
        stored = service.get(state.run_id)
        assert stored.status == expected
        assert "private-key" not in stored.model_dump_json()
        if outcome == "error":
            assert stored.error == "An agent could not complete its execution."
        if expected == "failed":
            assert stored.error_detail.agent_id == "maintainability_manager"
            assert stored.error_detail.invocation_id == state.invocation_id
            assert stored.error_detail.occurred_at is not None
            assert service.snapshot(state.run_id).error_detail == stored.error_detail
        else:
            assert stored.error_detail is None
        await service.aclose()

    asyncio.run(execute())
    audit_environment.client.close.assert_called_once()
    audit_environment.async_client.aclose.assert_awaited_once()


def test_actual_manager_publishes_a_failed_unsupported_scope_without_provider_calls(audit_environment):
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "request": {"dimensions": ["unsupported"]}})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        service = app.state.audit_service

        async def finish():
            task = service._tasks.get(run_id)
            if task is not None:
                await task

        client.portal.call(finish)
        assert client.get(f"/api/audits/{run_id}").json()["status"] == "failed"
        assessments = app.state.blackboard.query_assessments(run_id)
        assert len(assessments) == 1 and assessments[0].status == "failed"
        assert assessments[0].details["report"]["scope"]["unsupported"] == ["unsupported"]


def test_shutdown_cancels_running_audits_before_releasing_blackboard(audit_environment, monkeypatch):
    entered = asyncio.Event()

    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, tools, request):
            with tools.timing.quota_wait():
                entered.set()
                await asyncio.Event().wait()

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root)})
        run_id = response.json()["run_id"]
        client.portal.call(entered.wait)
        service = app.state.audit_service
        task = service._tasks[run_id]
    assert task.cancelled()
    assert service.get(run_id).status == "cancelled" and not service._tasks
    assert not hasattr(app.state, "audit_service")
    audit_environment.async_client.aclose.assert_awaited_once()


def test_timeout_is_recorded_and_releases_clients(audit_environment, monkeypatch):
    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, tools, request):
            await asyncio.Event().wait()

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)

    async def execute():
        from server.agents.maintainability.manager import MaintainabilityRequest
        from server.api.schemas import ExecutionConfig

        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), MaintainabilityRequest(), ExecutionConfig(timeout_seconds=1), "dummy")
        await service._tasks[state.run_id]
        assert service.get(state.run_id).error == "The execution exceeded its allowed time."
        assert service.get(state.run_id).status == "failed"
        assert service.get(state.run_id).error_detail.code == "execution_timeout"
        assert service.get(state.run_id).error_detail.exception_type == "TimeoutError"
        await service.aclose()

    asyncio.run(execute())
    audit_environment.async_client.aclose.assert_awaited_once()


def test_audit_stays_running_during_quota_wait_and_resumes_after_timeout_duration(audit_environment, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, tools, request):
            with tools.timing.quota_wait(reason="provider_retry_after", seconds=69273,
                    source="google.rpc.RetryInfo.retryDelay"):
                entered.set()
                await release.wait()
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "config": {"timeout_seconds": 1}})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        client.portal.call(entered.wait)
        client.portal.call(asyncio.sleep, 1.2)
        waiting = client.get(f"/api/audits/{run_id}").json()
        assert waiting["status"] == "running"
        assert waiting["waiting"][0]["source"] == "google.rpc.RetryInfo.retryDelay"
        assert waiting["waiting"][0]["reason"] == "provider_retry_after"
        assert waiting["waiting"][0]["agent_id"] == "maintainability_manager"
        task = app.state.audit_service._tasks[run_id]

        async def resume():
            release.set()
            await task

        client.portal.call(resume)
        assert client.get(f"/api/audits/{run_id}").json()["status"] == "completed"
        assert client.get(f"/api/audits/{run_id}").json()["waiting"] == []
    audit_environment.async_client.aclose.assert_awaited_once()


def test_rejects_invalid_paths_and_configuration_before_scheduling(audit_environment):
    with TestClient(app) as client:
        for path in [audit_environment.root.parent, audit_environment.root.parent / "missing"]:
            assert client.post("/api/audits", json={"repository_path": str(path)}).status_code == 422
        assert client.post("/api/audits", json={}).status_code == 422
        assert client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "config": {"timeout_seconds": 0}}).status_code == 422
        audit_environment.resolver.side_effect = InvalidConfigError("model.name is required")
        assert client.post("/api/audits", json={"repository_path": str(audit_environment.root)}).status_code == 422
        assert client.get("/api/audits/unknown").status_code == 404
        assert not app.state.audit_service._tasks
    audit_environment.factory.assert_not_called()


@pytest.mark.parametrize(("overrides", "code"), [
    ({"coordinator": {"max_model_calls": 30}}, "coordinator_call_budget_too_small"),
    ({"coordinator": {"max_tool_calls": 30}}, "coordinator_tool_budget_too_small"),
    ({"manager": {"max_tool_calls": 96}}, "manager_tool_budget_too_small"),
])
def test_undersized_hierarchy_call_limit_is_rejected_before_scheduling(audit_environment, overrides, code):
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "call_limits": overrides})
        assert response.status_code == 422
        assert code in response.text
        assert not app.state.audit_service._tasks


@pytest.mark.parametrize("global_tokens", [None, 3000000])
@pytest.mark.parametrize("tool_overrides", [False, True])
def test_common_developer_defaults_reach_the_full_hierarchy_and_repository_budget(audit_environment, monkeypatch, global_tokens, tool_overrides):
    from server.agents.maintainability.manager.config import MaintainabilityConfig
    from server.agents.maintainability.manager.execution import (
        MaintainabilityManagerExecution,
    )
    from server.agents.maintainability.manager.registry import COORDINATORS
    from server.agents.maintainability.modularity.coordinator.registry import (
        INVESTIGATORS as MODULARITY,
    )
    from server.agents.maintainability.reusability.coordinator.registry import (
        INVESTIGATORS as REUSABILITY,
    )
    from server.runtimes.coordination.execution import CoordinatorExecution

    finished = asyncio.Event()

    class Manager:
        def __init__(self, model, limits, **kwargs):
            self.limits = limits

        async def run(self, tools, request):
            assert self.limits.max_context_characters == 160000
            assert self.limits.max_total_tokens == 500000
            assert self.limits.max_model_calls == MaintainabilityConfig().max_model_calls
            assert self.limits.max_tool_calls == (300 if tool_overrides else MaintainabilityConfig().max_tool_calls)
            for dimension, spec in COORDINATORS.items():
                # Exercise the same conversion used by the actual runtime, including
                # each specialized investigator contract rather than only envelopes.
                coordinator = MaintainabilityManagerExecution.invocation_config(None, spec, self.limits.invocation_limits)
                assert coordinator.max_context_characters == 160000
                assert coordinator.max_total_tokens == 500000
                assert coordinator.max_model_calls == MaintainabilityConfig().invocation_limits.max_model_calls
                assert coordinator.max_tool_calls == (100 if tool_overrides else MaintainabilityConfig().invocation_limits.max_tool_calls)
                investigators = MODULARITY if dimension == "modularity" else REUSABILITY
                for child_spec in investigators.values():
                    child = CoordinatorExecution.invocation_config(None, child_spec, coordinator.invocation_limits)
                    assert child.max_context_characters == 160000
                    assert child.max_total_tokens == 500000
                    assert child.max_model_calls == 30
                    assert child.max_tool_calls == (25 if tool_overrides else 20)
            expected_global = global_tokens if global_tokens is not None else 1000000
            assert tools.context.input.budget.max_total_tokens == expected_global
            assert tools.token_budget.limit == expected_global
            assert tools.context.input.budget.max_input_tokens_per_call == 80000
            assert tools.context.input.budget.max_model_calls == MaintainabilityConfig().max_model_calls
            assert tools.context.input.budget.max_tool_calls == self.limits.max_tool_calls
            finished.set()
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    with TestClient(app) as client:
        body = {"repository_path": str(audit_environment.root),
            "agent_defaults": {"max_context_characters": 160000, "max_total_tokens": 500000,
                "max_model_calls": 30, "max_tool_calls": 20}}
        if tool_overrides:
            body["call_limits"] = {"manager": {"max_tool_calls": 300}, "coordinator": {"max_tool_calls": 100},
                "investigator": {"max_tool_calls": 25}}
        if global_tokens is not None:
            body["audit_budget"] = {"max_total_tokens": global_tokens}
        response = client.post("/api/audits", json=body)
        assert response.status_code == 202
        run_id = response.json()["run_id"]

        async def wait():
            task = app.state.audit_service._tasks.get(run_id)
            if task is not None:
                await task

        client.portal.call(wait)
        assert finished.is_set()
        assert client.get(f"/api/audits/{run_id}").json()["status"] == "completed"


@pytest.mark.parametrize("defaults", [
    {"max_context_characters": 3999}, {"max_total_tokens": 0},
    {"max_context_characters": None}, {"max_total_tokens": None},
    {"max_model_calls": 0}, {"max_model_calls": None}, {"max_model_calls": 3},
    {"max_tool_calls": 50}, {"max_tool_calls": -1}, {"max_tool_calls": None},
    {"invocation_limits": {"max_total_tokens": 500000}},
])
def test_invalid_or_unapproved_defaults_do_not_schedule_tasks(audit_environment, defaults):
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "agent_defaults": defaults})
        assert response.status_code == 422
        assert not app.state.audit_service._tasks
    audit_environment.factory.assert_not_called()


def test_invalid_global_token_cap_is_rejected_before_scheduling(audit_environment):
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "audit_budget": {"max_total_tokens": 0}})
        assert response.status_code == 422
        assert not app.state.audit_service._tasks
    audit_environment.factory.assert_not_called()


def test_partial_defaults_preserve_agent_specific_values():
    from config.agents.audit import AuditAgentDefaults, apply_audit_defaults
    from server.agents.maintainability.manager import MaintainabilityConfig

    original = MaintainabilityConfig()
    context_only = apply_audit_defaults(original, AuditAgentDefaults(max_context_characters=160000))
    before, after = original, context_only
    while True:
        expected = before.model_dump(exclude={"invocation_limits", "max_context_characters"})
        assert after.model_dump(exclude={"invocation_limits", "max_context_characters"}) == expected
        assert after.max_context_characters == 160000
        if not hasattr(before, "invocation_limits"):
            break
        before, after = before.invocation_limits, after.invocation_limits
    assert apply_audit_defaults(original, AuditAgentDefaults()) == original
    assert MaintainabilityConfig() == original


def test_shutdown_cancels_audit_that_has_not_started_yet(audit_environment):
    async def execute():
        from server.agents.maintainability.manager import MaintainabilityRequest
        from server.api.schemas import ExecutionConfig

        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), MaintainabilityRequest(), ExecutionConfig(), "dummy")
        snapshot = service.snapshot(state.run_id)
        assert snapshot.status == "queued"
        assert snapshot.evidence == snapshot.findings == snapshot.assessments == []
        assert service.snapshot("unknown") is None
        await service.aclose()
        assert service.get(state.run_id).status == "cancelled"
        assert not service._tasks

    asyncio.run(execute())
    audit_environment.factory.assert_not_called()


@pytest.mark.parametrize("fail", [False, True])
def test_status_includes_live_records_and_preserves_them_after_completion_or_failure(audit_environment, monkeypatch, fail):
    entered, publish_more, published, finish = (asyncio.Event() for _ in range(4))

    class Manager:
        def __init__(self, model, limits, *, blackboard, audit_identity, tracing_backend):
            self.board, self.identity = blackboard, audit_identity

        async def run(self, tools, request):
            evidence = Evidence(id="evidence", agent_id="investigator", run_id=self.identity.run_id,
                invocation_id="worker", kind="source", source="main.py", snapshot_hash=tools.context.input.snapshot_hash,
                file_id="file", content_hash="hash", tool_call_id="read", start_line=1, end_line=2,
                details={"source_note": "Original observation"})
            finding = Finding(id="finding", agent_id="investigator", run_id=self.identity.run_id,
                invocation_id="worker", title="Uncertain finding", description="Consumer needs inspection",
                kind="design_observation", criterion_id="rule", criterion={"id": "rule", "description": "Inspect",
                    "origin": "inferred", "provenance": "Test"}, components=["component"],
                justification="Partial inspection", modularity_impact="Unknown", evidence_ids=[evidence.id],
                confidence=None, severity=None, details={"validation_status": "insufficient_evidence", "category": "coupling"})
            assessment = Assessment(id="assessment", agent_id="coordinator", run_id=self.identity.run_id,
                invocation_id="coordinator", repository_id=tools.accessible_snapshot.repository.name,
                snapshot_hash=tools.context.input.snapshot_hash, objective=request.objective,
                status="partial", termination_reason="missing_evidence", finding_ids=[finding.id], evidence_ids=[evidence.id],
                limitations=["Consumer unavailable"], details={"domain_analysis": {"conclusion": "unknown"}})
            self.board.publish_evidence(evidence)
            self.board.publish_evidence(evidence.model_copy(update={"run_id": "other-audit", "details": {"foreign": True}}))
            self.board.publish_finding(finding.model_copy(update={"run_id": "other-audit", "details": {"foreign": True}}))
            self.board.publish_assessment(assessment.model_copy(update={"run_id": "other-audit", "details": {"foreign": True}}))
            entered.set()
            await publish_more.wait()
            self.board.publish_finding(finding)
            self.board.publish_assessment(assessment)
            published.set()
            await finish.wait()
            if fail:
                raise RuntimeError("private-key must not appear")
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    with TestClient(app) as client:
        response = client.post("/api/audits", json={"repository_path": str(audit_environment.root)})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        url = f"/api/audits/{run_id}"
        client.portal.call(entered.wait)
        early_response = client.get(url)
        assert early_response.headers["cache-control"] == "no-store"
        early = early_response.json()
        assert early["status"] == "running"
        assert [record["id"] for record in early["evidence"] if record["kind"] == "source"] == ["evidence"]
        assert any("audit_context" in record["details"] for record in early["evidence"])
        catalog = next(record["details"]["audit_context"]["entity_catalog"] for record in early["evidence"]
            if "audit_context" in record["details"])
        assert any(item["kind"] == "file" and item["path"] for item in catalog)
        assert all("content" not in item for item in catalog)
        assert early["findings"] == early["assessments"] == []
        client.portal.call(publish_more.set)
        client.portal.call(published.wait)
        current = client.get(url).json()
        assert current["status"] == "running"
        assert [record["id"] for record in current["findings"]] == ["finding"]
        assert [record["id"] for record in current["assessments"]] == ["assessment"]
        assert current["findings"][0]["confidence"] is None
        assert current["findings"][0]["details"]["validation_status"] == "insufficient_evidence"
        assert current["assessments"][0]["limitations"] == ["Consumer unavailable"]
        assert current["assessments"][0]["details"]["domain_analysis"] == {"conclusion": "unknown"}
        assert all(record["run_id"] == run_id and "foreign" not in record["details"]
            for kind in ("evidence", "findings", "assessments") for record in current[kind])
        repeated = client.get(url).json()
        assert repeated["activity"][0]["started_at"] == current["activity"][0]["started_at"]
        assert repeated["activity"][0]["elapsed_seconds"] >= current["activity"][0]["elapsed_seconds"]
        assert repeated["wall_seconds_remaining"] <= current["wall_seconds_remaining"]
        dynamic = {"activity", "active_seconds_remaining", "wall_seconds_remaining"}
        assert {k: v for k, v in repeated.items() if k not in dynamic} == {k: v for k, v in current.items() if k not in dynamic}
        assert client.get("/api/audits/other-audit").status_code == 404
        report_response = client.get(url + "/report")
        assert report_response.status_code == 200
        assert report_response.headers["cache-control"] == "no-store"
        assert report_response.json()["identification"]["audit_id"] == run_id
        assert report_response.json()["identification"]["status"] == "partial"
        assert report_response.json()["software_description"]["languages"] == ["python"]
        assert client.get("/api/audits/other-audit/report").status_code == 404
        task = app.state.audit_service._tasks[run_id]

        async def complete():
            finish.set()
            await task

        client.portal.call(complete)
        final = client.get(url).json()
        assert final["status"] == ("failed" if fail else "completed")
        for kind in ("findings", "assessments"):
            assert final[kind] == current[kind]
        assert all(record in final["evidence"] for record in current["evidence"])
        assert any(record["details"].get("audit_outcome", {}).get("status") == final["status"]
            for record in final["evidence"])
        final_report = client.get(url + "/report").json()
        assert final_report["identification"]["status"] == ("failed" if fail else "partial")
        assert "private-key" not in client.get(url).text


def test_shutdown_waits_for_cleanup_of_a_completed_audit(audit_environment, monkeypatch):
    class Manager:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, tools, request):
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)

    async def execute():
        from server.agents.maintainability.manager import MaintainabilityRequest
        from server.api.schemas import ExecutionConfig

        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def close():
            entered.set()
            await release.wait()
            finished.set()

        audit_environment.async_client.aclose.side_effect = close
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), MaintainabilityRequest(), ExecutionConfig(), "dummy")
        await entered.wait()
        assert service.get(state.run_id).status == "completed"
        shutdown = asyncio.create_task(service.aclose())
        release.set()
        await shutdown
        assert finished.is_set()

    asyncio.run(execute())
