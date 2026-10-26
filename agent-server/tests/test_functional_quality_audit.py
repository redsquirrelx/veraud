import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_quality_audit_pipeline import _committed_checkout, _RecordingSink

from server.agents.functional_adequacy.agent import FunctionalAdequacyAgent
from server.agents.functional_adequacy.schemas import CodeEvidence
from server.api.schemas import ExecutionConfig
from server.app import audit_service, quality_audit_definition
from server.app.audit_models import MAINTAINABILITY_AGENT_TYPES
from server.app.execution_service import InvalidConfigError
from server.app.pipeline_service import GenericPipelineService
from server.blackboard.impls.memory import MemoryBlackboard
from server.blackboard.models import Assessment
from server.infrastructure.tracing import NoOpTracingBackend

pytest_plugins = ["test_audits"]


@pytest.mark.parametrize("source", ["category", "individual"])
def test_impossible_output_is_rejected_before_accepting_an_audit(audit_environment, source):
    from config.agents.audit import AuditAgentDefaults

    service = audit_service.AuditService(MemoryBlackboard())
    with pytest.raises(InvalidConfigError, match="tokens_per_minute"):
        service.start(str(audit_environment.root), audit_service.MaintainabilityRequest(),
            ExecutionConfig(model={"max_tokens": 1000000} if source == "individual" else {}), "dummy",
            attributes=["functional_adequacy"],
            functional_requirements=[{"requirement_id": "REQ-001", "description": "Devolver el número solicitado."}],
            agent_defaults=AuditAgentDefaults(max_output_tokens=1000000) if source == "category" else None)


@pytest.mark.parametrize("attributes", [["functional_adequacy"], ["maintainability", "functional_adequacy"],
    ["security", "functional_adequacy"], ["maintainability", "security", "functional_adequacy"]])
@pytest.mark.parametrize("provider_failure", [False, True])
@pytest.mark.parametrize("output_override", [None, 24000])
def test_functional_attribute_runs_in_shared_quality_pipeline_with_live_receipts_and_portable_reports(
        audit_environment, monkeypatch, attributes, provider_failure, output_override):
    root = audit_environment.root
    commit = _committed_checkout(root)
    monkeypatch.setattr(quality_audit_definition, "resolve_workspace_root", lambda: root.parent)
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(side_effect=RuntimeError("private-provider-payload")) if provider_failure else AsyncMock(
        return_value=SimpleNamespace(content=json.dumps({"status": "no_cumple", "justification": "La función devuelve un valor constante."}),
            usage_metadata={"input_tokens": 20, "output_tokens": 5}))

    # Keep retrieval deterministic and offline; the existing SBERT test covers ranking.
    def retrieve(self, state):
        assert self.config.retrieval_top_k == 2
        assert self.config.max_context_characters == 220000
        assert self.config.max_output_tokens == (output_override or 16000)
        fragment = next(item for item in state["input_data"].code_fragments if item.file_path.startswith("main.py:"))
        return {"candidates": {requirement.requirement_id: [CodeEvidence(fragment_id=fragment.fragment_id,
            file_path=fragment.file_path, similarity=0.9)] for requirement in state["input_data"].requirements}}

    monkeypatch.setattr(FunctionalAdequacyAgent, "_retrieve_candidates", retrieve)

    class Manager:
        def __init__(self, model, limits, *, blackboard, audit_identity, tracing_backend):
            assert limits.max_context_characters == 330000
            self.board, self.identity = blackboard, audit_identity

        async def run(self, tools, request):
            self.board.publish_assessment(Assessment(agent_id="maintainability_manager", run_id=self.identity.run_id,
                invocation_id=self.identity.invocation_id, quality_attribute="maintainability",
                repository_id=tools.accessible_snapshot.repository.name, snapshot_hash=tools.context.input.snapshot_hash,
                objective=request.objective, status="complete", termination_reason="sufficient_coverage"))
            return SimpleNamespace(status="complete")

    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Manager)
    sink = _RecordingSink()
    stage = "maintainability_manager" if "maintainability" in attributes else (
        "security" if "security" in attributes else "functional_adequacy")
    participants = [*(MAINTAINABILITY_AGENT_TYPES if "maintainability" in attributes else ()),
        *(("security",) if "security" in attributes else ()), "functional_adequacy"]

    async def run():
        return (await GenericPipelineService(callbacks_factory=lambda: sink, tracing_backend=NoOpTracingBackend()).run(
            "quality-audit", {"root_path": str(root), "commit_hash": commit, "attributes": attributes,
                "attribute_options": {attribute: ({"agent_defaults": {"max_context_characters": 330000}} if attribute == "maintainability"
                    else {"security_config": {"max_scan_files": 1}} if attribute == "security"
                    else {"agent_defaults": {"max_context_characters": 220000, "max_output_tokens": 16000}, "functional_config": {"retrieval_top_k": 2}})
                    for attribute in attributes},
                "functional_requirements": [{"requirement_id": "REQ-001", "description": "Devolver el número solicitado."}]},
             ExecutionConfig(), stage_configs={name: ExecutionConfig(model={"provider": "openai", "name": name,
                 "max_tokens": output_override if name == "functional_adequacy" else None}, api_key="private-key")
                for name in participants}, execution_ids={stage: 42}))["audit"]

    payload = asyncio.run(run())
    assert any(call.kwargs.get("max_tokens") == (output_override or 16000) for call in model.ainvoke.await_args_list)
    assert payload["status"] == ("partial" if provider_failure else "completed")
    functional = next(item for item in payload["blackboard"]["assessments"] if item["agent_id"] == "functional_adequacy")
    assert functional["run_id"] == payload["run_id"]
    assert functional["details"]["functional_output"]["results"][0]["status"] == (
        "evidencia_insuficiente" if provider_failure else "no_cumple")
    assert {item["quality_attribute"] for item in payload["blackboard"]["assessments"]} == set(attributes)
    assert base64.b64decode(payload["docx_base64"]).startswith(b"PK")
    traces = [receipt for execution_id, receipt in sink.invocations if receipt["agent_id"] == "functional_adequacy"]
    assert list(dict.fromkeys(trace["phase"] for trace in traces if trace.get("phase"))) == [
        "prepare", "code_mapping", "verify", "build_results"]
    assert traces[-1]["phase"] is None
    assert traces[0]["status"] == "running" and traces[-1]["status"] == ("partial" if provider_failure else "completed")
    assert traces[-1]["input_tokens"] == (None if provider_failure else 20)
    findings = payload["report"]["quality_results"]["findings"]
    assert any(item["quality_attribute"] == "functional_adequacy" for item in findings)
    assert all(item["verification_status"] != "verified" for item in findings if item["quality_attribute"] == "functional_adequacy")
    assert "private-provider-payload" not in str(payload) and "private-key" not in str(payload)
    audit_environment.async_client.aclose.assert_awaited_once()


@pytest.mark.parametrize("requirements", [None, [], [{"requirement_id": "same", "description": "One"},
    {"requirement_id": "same", "description": "Two"}], [{"requirement_id": "blank", "description": " "}]])
def test_functional_requirements_are_validated_before_audit_execution(requirements):
    with pytest.raises(InvalidConfigError):
        quality_audit_definition.parse_input({"root_path": "checkout", "commit_hash": "a" * 40,
            "attributes": ["functional_adequacy"], "functional_requirements": requirements})
