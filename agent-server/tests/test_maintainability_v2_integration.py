"""Production pipeline, real V2 agents, repository tools and web-facing receipts."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from test_architecture_boundary_doc_driven_investigation import (
    Model,
    assess_all,
    verified_tools,
)
from test_architecture_boundary_doc_driven_planning import claim, context
from test_quality_audit_pipeline import _RecordingSink

from server.app import audit_service, quality_audit_definition
from server.app.execution_config import ExecutionConfig
from server.app.pipeline_service import GenericPipelineService
from server.config.schemas import ModelCredentials, ModelSettings
from server.infrastructure.tracing import NoOpTracingBackend
from server.reporting.snapshot import BlackboardSnapshot, report_from_snapshot


def test_quality_pipeline_executes_only_v2_and_returns_portable_unreviewed_findings(tmp_path, monkeypatch):
    tools = verified_tools(tmp_path, {"app/__init__.py": "", "app/api.py": "from .store import Store\ndef use(): return Store()\n",
        "app/store.py": "class Store: pass\n"})
    root = tmp_path / "repo"
    documented = context(tools, [claim()])
    from server.agents.maintainability.v2.modularity.coordinator import dispatch

    original_request = dispatch.investigator_request
    sent_requests = []

    def capture_request(*args, **kwargs):
        sent = original_request(*args, **kwargs)
        sent_requests.append(sent)
        return sent

    monkeypatch.setattr(dispatch, "investigator_request", capture_request)

    class PipelineModel(Model):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[1].content)
            if "coordinator_catalog" in payload:
                assert "documented_architecture" not in payload["request"]
                assert documented.knowledge[0].statement not in messages[1].content
                value = {"objective": "Inspect boundaries.", "assignments": [{"coordinator_id": "modularity",
                    "objective": "Inspect boundaries.", "scope": ["app"], "constraints": [], "rationale": "Architectural scope."}]}
            elif "investigator_catalog" in payload:
                assert "documented_architecture" not in payload["request"]
                assert documented.knowledge[0].statement not in messages[1].content
                value = {"objective": "Inspect boundaries.", "assignments": [{"investigator_id": "architecture_boundary",
                    "objective": "Coordinator objective must not reach the investigator.", "targets": ["app"], "constraints": [],
                    "rationale": "Documentary obligations supplied."}]}
            else:
                return await super().ainvoke(messages, **kwargs)
            return AIMessage(content=json.dumps(value), usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})

    model = PipelineModel(lambda payload: assess_all(payload, "contradicted", status="finding_candidate", candidate=True))
    monkeypatch.setattr(audit_service, "resolve_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(audit_service, "resolve_model_settings", lambda *args: (
        ModelSettings(provider="openai", name="offline", temperature=0.2, max_tokens=1000), ModelCredentials(api_key="private-test-key"), 300))
    monkeypatch.setattr(audit_service, "build_chat_model", lambda *args: model)
    monkeypatch.setattr(audit_service, "LangSmithTracingBackend", NoOpTracingBackend)
    monkeypatch.setattr(audit_service, "close_model_clients", AsyncMock())

    class Sink(_RecordingSink):
        def __init__(self):
            super().__init__()
            self.activity = []

        async def events(self, execution_id, events):
            self.activity.extend(events)
            from server.agent_services.execution_tracking.callback.schemas import (
                CallbackResult,
            )
            return CallbackResult(acknowledged=True)

    sink = Sink()

    async def execute():
        service = GenericPipelineService(callbacks_factory=lambda: sink, tracing_backend=NoOpTracingBackend())
        payload = (await service.run("quality-audit", {"root_path": str(root), "commit_hash": tools.accessible_snapshot.repository.commit,
            "attributes": ["maintainability"], "maintainability_selection": {"modularity": ["architecture_boundary"]},
            "request": {"objective": "Inspect architectural boundaries.", "targets": ["app"],
                "documented_architecture": documented.model_dump(mode="json")},
            "call_limits": {"manager": {"max_model_calls": 48, "max_tool_calls": 90},
                "coordinator": {"max_model_calls": 32, "max_tool_calls": 60}},
        }, ExecutionConfig(), execution_ids={"maintainability_manager": 42}))["audit"]
        from server.agent_services.execution_tracking.buffer import (
            deliver_execution_events,
            execution_event_buffer,
        )
        await deliver_execution_events(execution_event_buffer(), sink)
        restored = await report_from_snapshot(BlackboardSnapshot.model_validate({"run_id": payload["run_id"],
            **{key: payload["blackboard"][key] for key in ("assessments", "findings", "evidence")}}))
        return payload, restored

    payload, restored = asyncio.run(execute())
    assert sent_requests
    assert all(sent.documented_architecture == documented for sent in sent_requests)
    assert payload["status"] == "completed"
    assert payload["docx_base64"] and restored.identification.audit_id == payload["run_id"]
    assert "private-test-key" not in json.dumps(payload)
    receipts = {receipt["agent_id"]: receipt for _, receipt in sink.invocations}
    assert set(receipts) == {"maintainability_manager", "modularity", "architecture_boundary"}
    assert all(receipt["status"] == "completed" and receipt["run_id"] == payload["run_id"] for receipt in receipts.values())
    assert receipts["modularity"]["parent_invocation_id"] == receipts["maintainability_manager"]["invocation_id"]
    assert receipts["architecture_boundary"]["parent_invocation_id"] == receipts["modularity"]["invocation_id"]
    assert sink.activity
    findings = payload["blackboard"]["findings"]
    assert findings and all(not {"validation_status", "review_rationale"} & finding["details"].keys() for finding in findings)
    assert payload["report"]["executive_summary"]["findings"]["by_verification"]["unreviewed"] == len(findings)


@pytest.mark.parametrize("selection", [{"reusability": ["legacy_abstraction"]}, {"modularity": []}, {"reusability": ["responsibility"]}, {"unknown": []}])
def test_pipeline_rejects_legacy_or_empty_selections_before_execution(selection):
    from server.app.errors import InvalidConfigError
    with pytest.raises(InvalidConfigError):
        quality_audit_definition.parse_input({"root_path": "unused", "commit_hash": "a" * 40,
            "attributes": ["maintainability"], "maintainability_selection": selection})


def test_v2_child_without_output_remains_visible_in_web_diagnostics():
    from server.blackboard.models import Assessment
    from server.services.audit_diagnostics import execution_diagnostics

    record = Assessment(agent_id="maintainability_manager", run_id="run", invocation_id="root",
        repository_id="repo", snapshot_hash="snapshot", objective="Inspect boundaries", status="failed", termination_reason="audit_failed",
        details={"report": {"coordinator_results": [{"assignment_id": "child", "assignment": {"coordinator_id": "modularity"},
            "status": "failed", "result": None, "failure": {"code": "execution_budget_exhausted", "summary": "No child budget."}}]}})
    diagnostics = execution_diagnostics([record])
    assert any(issue.invocation_id == "child" and issue.agent_id == "modularity" and issue.status == "failed" for issue in diagnostics)
