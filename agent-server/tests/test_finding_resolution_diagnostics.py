"""Diagnostics preserve execution decisions and exclude untrusted payloads."""

import asyncio
import json
from typing import ClassVar

import pytest
import test_finding_resolution as shared
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from test_finding_resolution import PlanningModel, planning_agent
from test_finding_resolution_investigation import ask, close
from test_finding_resolution_recovery import Model, request_for

from server.agents.finding_resolution import FindingResolutionRequest
from server.runtimes.repository.context import RepositoryContext

finding = shared.finding
tools = shared.tools


def events(caplog, prefix="finding_resolution_diagnostic "):
    return [json.loads(item.getMessage()[len(prefix):]) for item in caplog.records if item.getMessage().startswith(prefix)]


@pytest.mark.parametrize(("kind", "category", "field", "rule"), [
    ("missing", "pydantic_validation", "checks.0.resolved_if", "missing"),
    ("arguments", "tool_arguments", "checks.0.queries.0.arguments.start_line", "greater_than_equal"),
    ("disabled", "agent_validation", "checks.0.queries.0.name", "enabled_repository_tool"),
    ("identity", "agent_validation", "finding_id", "current_finding_id"),
])
def test_plan_rejections_report_exact_field_and_rule(finding, tools, caplog, kind, category, field, rule):
    caplog.set_level("INFO", logger="server.finding-resolution")
    def respond(context):
        plan = PlanningModel.plan(context)
        if kind == "missing":
            del plan["checks"][0]["resolved_if"]
        elif kind == "arguments":
            plan["checks"][0]["queries"][0]["arguments"]["start_line"] = 0
        elif kind == "disabled":
            plan["checks"][0]["queries"][0]["name"] = "write_file"
        else:
            plan["finding_id"] = "other"
        return plan
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    state = asyncio.run(planning_agent(PlanningModel(respond), max_schema_retries=0).run(request, tools=tools))
    event = events(caplog)[0]
    assert event["category"] == category and event["finding_id"] == finding.id and event["node"] == "plan_verification"
    assert event["issues"][0]["field"] == field and event["issues"][0]["rule"] == rule
    if kind == "arguments":
        assert event["issues"][0]["constraints"] == {"ge": 1}
    assert state["termination_reason"] == "model_or_schema_error" and not state["plans"]
    assert state["consumption"].model_calls == 1 and state["consumption"].tool_calls == 0
    assert "response unavailable or invalid" not in caplog.text
    assert any(getattr(record, "finding_resolution_diagnostic", None) == event for record in caplog.records)


@pytest.mark.parametrize("native", [False, True])
def test_malformed_responses_are_not_reported_as_provider_failures(finding, tools, caplog, native):
    caplog.set_level("INFO", logger="server.finding-resolution")
    model = Model(lambda context: "{not JSON")
    if native:
        class Structured:
            def __init__(self, schema):
                self.schema = schema
            async def ainvoke(self, messages, **kwargs):
                raw = await model.ainvoke(messages, **kwargs)
                try:
                    parsed = self.schema.model_validate_json(raw.content)
                except ValidationError as error:
                    return {"raw": raw, "parsing_error": error}
                return {"raw": raw, "parsed": parsed}
        model.with_structured_output = lambda schema, **kwargs: Structured(schema)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    state = asyncio.run(planning_agent(model, max_schema_retries=0).run(request, tools=tools))
    event = events(caplog)[0]
    assert event["category"] == "malformed_response" and event["node"] == "investigate"
    assert event["issues"][0]["rule"] in {"invalid_json", "json_invalid"}
    assert state["investigations"][0].stop_reason == "model_or_schema_error"
    summary = events(caplog, "finding_resolution_summary ")[0]
    assert summary["global_stop"] is None and summary["individual_error_attempts"] == 1
    assert summary["global_errors"] == [] and summary["pending_finding_ids"] == []


def test_provider_error_has_safe_protocol_details_not_exception_payload(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    class ProviderError(ValueError):
        status_code = 400
        body: ClassVar = {"error": {"status": "INVALID_ARGUMENT", "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest",
            "fieldViolations": [{"field": "response_json_schema", "description": "password=PRIVATE_PAYLOAD"}]}]}}
    def fail(context):
        raise ProviderError("api_key=PRIVATE_PAYLOAD def secret_source(): pass")
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    state = asyncio.run(planning_agent(Model(fail), max_schema_retries=0).run(request, tools=tools))
    event = events(caplog)[0]
    assert event["category"] == "provider" and event["scope"] == "global" and event["http_status"] == 400
    assert "response_json_schema" in event["provider_facts"] and event["error_type"] == "ProviderError"
    assert "PRIVATE_PAYLOAD" not in caplog.text and "secret_source" not in caplog.text
    assert state["termination_reason"] == "model_or_schema_error"
    assert events(caplog, "finding_resolution_summary ")[0]["global_errors"]


def test_adapter_parser_exception_is_not_mislabelled_as_transport_failure(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    def fail(context):
        raise OutputParserException("PRIVATE_PARSE_TEXT", llm_output="PRIVATE_MODEL_RESPONSE")
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    state = asyncio.run(planning_agent(Model(fail), max_schema_retries=0).run(request, tools=tools))
    event = events(caplog)[0]
    assert event["category"] == "malformed_response" and event["issues"][0]["rule"] == "output_parser_error"
    assert state["termination_reason"] == "model_or_schema_error"  # Original provider-adapter stopping policy.
    assert "PRIVATE_PARSE_TEXT" not in caplog.text and "PRIVATE_MODEL_RESPONSE" not in caplog.text


def test_generation_truncation_is_identifiable(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    class TruncatedModel(Model):
        async def ainvoke(self, messages, **kwargs):
            if "plan" in json.loads(messages[1].content):
                return AIMessage(content="{", response_metadata={"finish_reason": "MAX_TOKENS"},
                    usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})
            return await super().ainvoke(messages, **kwargs)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    asyncio.run(planning_agent(TruncatedModel(lambda context: None), max_schema_retries=0).run(request, tools=tools))
    event = events(caplog)[0]
    assert event["category"] == "generation" and event["generation_outcome"] == "output_token_limit_reached"


def test_structured_generation_setup_error_is_reported_without_a_provider_call(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    class SetupFailure(PlanningModel):
        def with_structured_output(self, schema, **kwargs):
            raise ValueError("api_key=PRIVATE_SETUP_PAYLOAD")
    model = SetupFailure()
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    state = asyncio.run(planning_agent(model).run(request, tools=tools))
    event = events(caplog)[0]
    assert event["category"] == "generation" and event["error_type"] == "ValueError"
    assert event["issues"][0]["rule"] == "structured_output_setup_failed"
    assert state["consumption"].model_calls == 0 and model.contexts == []
    assert "PRIVATE_SETUP_PAYLOAD" not in caplog.text and "response unavailable or invalid" not in caplog.text


def test_recoverable_failure_summary_separates_findings_from_global_stop(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    tools.context = RepositoryContext(tools.context.snapshot, tools.context.input.model_copy(update={
        "budget": tools.context.input.budget.model_copy(update={"max_model_calls": 16})}))
    def decide(context):
        if not context["tool_results"]:
            return ask(context)
        return close(context, evidence_ids=["invented"]) if context["finding"]["id"] == "middle" else close(context)
    state = asyncio.run(planning_agent(Model(decide), max_model_calls=16, max_schema_retries=1).run(request_for(finding, tools), tools=tools))
    summary = events(caplog, "finding_resolution_summary ")[0]
    assert summary["termination_reason"] == state["termination_reason"] == "investigations_completed_with_errors"
    assert summary["global_stop"] is None and summary["pending_finding_ids"] == [] and summary["individual_error_attempts"] == 2
    assert summary["individual_results"][1]["stop_reason"] == "model_or_schema_error"
    assert summary["individual_results"][1]["evidence_count"] == 1
    errors = events(caplog)
    assert [item["attempt"] for item in errors] == [1, 2]
    assert all(item["issues"][0] == {"field": "evidence_ids", "rule": "current_finding_evidence_only"} for item in errors)
    assert "response unavailable or invalid" not in caplog.text
    assert state["consumption"].model_calls == 13 and "diagnostics" not in state


def test_plan_conditions_and_executed_search_are_visible_without_source_or_credentials(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    secret = "password=PRIVATE_QUERY def hidden_source(): pass"
    def decide(context):
        if not context["tool_results"]:
            return ask(context, "search_repository_text", {"query": secret})
        return close(context, limitations=["No source was retrieved for evaluation."])
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    asyncio.run(planning_agent(Model(decide)).run(request, tools=tools))
    traces = events(caplog, "finding_resolution_trace ")
    plan = next(item for item in traces if item["transition"] == "verification_plan")
    assert plan["checks"][0]["persists_if"] and plan["checks"][0]["resolved_if"] and plan["original_violation"]
    result = next(item for item in traces if item["transition"] == "tool_result")
    assert result["tool"] == "search_repository_text" and result["arguments"]["query"]["characters"] == len(secret)
    assert result["tool_call_id"] and "PRIVATE_QUERY" not in caplog.text and "hidden_source" not in caplog.text
    assert "def use(): return 1" not in caplog.text


@pytest.mark.parametrize(("payload", "rule"), [
    ('{"finding_id":"f1","finding_id":"f2"}', "duplicate_json_keys"),
    ('{"confidence":NaN}', "nonstandard_json_constant"),
])
def test_specific_json_parsing_rules_are_logged(finding, tools, caplog, payload, rule):
    caplog.set_level("INFO", logger="server.finding-resolution")
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    asyncio.run(planning_agent(Model(lambda context: payload), max_schema_retries=0).run(request, tools=tools))
    assert events(caplog)[0]["issues"][0]["rule"] == rule


def test_dubious_criteria_are_displayed_not_silently_rewritten_or_rejected(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    condition = "The developer states that the issue was fixed."
    def respond(context):
        if "plan" in context:
            return close(context, limitations=["No source inspected in this diagnostic test."])
        plan = PlanningModel.plan(context)
        plan["checks"][0]["resolved_if"] = condition
        return plan
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    state = asyncio.run(planning_agent(PlanningModel(respond)).run(request, tools=tools))
    trace = next(item for item in events(caplog, "finding_resolution_trace ") if item["transition"] == "verification_plan")
    assert trace["checks"][0]["resolved_if"] == condition
    assert trace["criteria_review"] == "generated_conditions_not_semantically_validated"
    assert state["plans"][0].checks[0].resolved_if == condition and state["consumption"].model_calls == 3


def test_untrusted_schema_values_and_criteria_do_not_leak_to_logs(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    def respond(context):
        plan = PlanningModel.plan(context)
        plan["checks"][0]["queries"][0]["arguments"]["PRIVATE_FIELD"] = "PRIVATE_VALUE"
        return plan
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    asyncio.run(planning_agent(PlanningModel(respond), max_schema_retries=0).run(request, tools=tools))
    assert events(caplog)[0]["issues"][0]["field"] == "checks.0.queries.0.arguments.<field>"
    assert "PRIVATE_FIELD" not in caplog.text and "PRIVATE_VALUE" not in caplog.text
    caplog.clear()
    condition = 'api_key="PRIVATE_VALUE" ```def private_source(): pass```'
    def criteria(context):
        if "plan" in context:
            return close(context, limitations=["No source inspected."])
        plan = PlanningModel.plan(context)
        plan["checks"][0]["resolved_if"] = condition
        return plan
    state = asyncio.run(planning_agent(PlanningModel(criteria)).run(request, tools=tools))
    assert state["plans"][0].checks[0].resolved_if == condition
    assert "PRIVATE_VALUE" not in caplog.text and "private_source" not in caplog.text
