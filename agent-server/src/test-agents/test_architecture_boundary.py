"""Legacy shared fixtures used by investigator tests.

Boundary's former analysis tests were replaced by
tests/test_architecture_boundary_planning.py. These helpers remain because
other investigators still use the same offline model and repository fixtures.
"""

import asyncio
import hashlib
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
    Criterion,
)
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import RepositoryAnalysisService

PLAN = {"objectives": ["Inspect domain boundary"], "components": ["domain", "storage"],
        "hypotheses": [{"id": "h1", "question": "Does domain depend on storage?",
                        "criterion_id": "domain-rule", "evidence_needed": ["domain source"]}]}


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.history = []
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, **kwargs):
        self.history.append(messages)
        value = next(self.responses)
        if callable(value):
            value = value(messages)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, AIMessage) else AIMessage(content=json.dumps(value))


class NativeStructuredModel(ScriptedModel):
    """Mimic LangChain's include_raw contract, including parsing-error envelopes."""

    def __init__(self, responses):
        super().__init__(responses)
        self.schemas = []

    def with_structured_output(self, schema, *, method, include_raw):
        self.schemas.append((schema.__name__, method, include_raw))
        parent = self

        class Structured:
            async def ainvoke(self, messages, **kwargs):
                raw = await parent.ainvoke(messages, **kwargs)
                try:
                    parsed = schema.model_validate(json.loads(raw.content))
                except (ValueError, TypeError) as error:
                    return {"raw": raw, "parsed": None, "parsing_error": error}
                return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return Structured()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    (root / "domain").mkdir(parents=True)
    (root / "storage").mkdir()
    (root / "domain" / "service.py").write_text("from storage.db import save\n\ndef execute():\n    save()\n")
    (root / "storage" / "db.py").write_text("def save():\n    return None\n")
    (root / "README.md").write_text("Domain must not depend on storage.\n")
    return root


def toolset(root, **overrides):
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    budget = ExecutionBudget(**({"max_model_calls": 16, "max_input_tokens_per_call": 50_000,
                                "max_tokens_per_objective": 300_000, "max_total_tokens": 300_000} | overrides))
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash, budget=budget,
    )), workspace_root=root.parent)


def request():
    return AuditRequest(criteria=[Criterion(id="domain-rule", description="Domain must not import storage.",
                                           origin="explicit", provenance="Caller-supplied project rule")])


def call(name="get_source_excerpt", arguments=None, identifier="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments or
        {"path": "domain/service.py", "start_line": 1, "end_line": 4}, "id": identifier}])


def evaluation(messages, sufficient=True, candidate=True):
    envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
    ids = [r["id"] for envelope in envelopes for r in envelope.get("evidence", [])]
    finding = {"id": "f1", "title": "Domain imports concrete storage", "description": "Direct storage dependency",
               "criterion_id": "domain-rule", "kind": "violation", "components": ["domain", "storage"],
               "evidence_ids": ids, "justification": "Import contradicts supplied rule.",
               "modularity_impact": "Storage changes affect domain.", "severity": "medium", "confidence": 0.9,
               "recommendation": "Inject a domain-owned abstraction."}
    context = json.loads(messages[1].content)
    scope = list(dict.fromkeys(item["path"] for item in context["evidence"] if item["id"] in ids and item["path"] == "domain/service.py"))
    support = [{"evidence_id": item["id"], "role": "dependency", "observation": "Direct import of storage.db"}
        for item in context["evidence"] if item["id"] in ids and item["path"] == "domain/service.py" and item["kind"] == "source"]
    checks = [{"subject_type": kind, "subject_id": identifier, "claim_kind": "dependency",
        "scope_paths": scope, "support": support} for kind, identifier in
        [("hypothesis", "h1"), *([("candidate", "f1")] if candidate else [])]] if support else []
    return {"sufficient": sufficient, "hypotheses": [dict(PLAN["hypotheses"][0], evidence_ids=ids,
             status="confirmed" if sufficient else "inconclusive")],
            "candidates": [finding] if candidate else [],
            "missing_information": [] if sufficient else ["Inspect storage endpoint"], "claim_checks": checks}


class BoundaryReviewResponse(dict):
    def __call__(self, messages):
        value = json.loads(json.dumps(self))
        context = json.loads(messages[1].content)
        evaluation = context["evaluation"]
        for finding in value["findings"]:
            checks = [item for item in evaluation.get("claim_checks", [])
                if item["subject_type"] == "candidate" and item["subject_id"] == finding["finding_id"]]
            finding.update(scope_supported=True, checked_evidence_ids=list(dict.fromkeys(
                support["evidence_id"] for check in checks for support in check["support"])))
        if "hypotheses" not in value:
            requirements = context.get("boundary_hypothesis_review_requirements", [{
                "hypothesis_id": subject["id"], "expected_checked_evidence_ids": subject["evidence_ids"],
            } for subject in evaluation.get("hypotheses", []) if subject["status"] in {"confirmed", "discarded"}])
            value["hypotheses"] = [{"hypothesis_id": item["hypothesis_id"], "status": "supported",
                "rationale": "The inspected source answers the stated bounded question.",
                "scope_supported": True, "checked_evidence_ids": item["expected_checked_evidence_ids"],
                "unverified_claims": []} for item in requirements]
        return value


def review(status="accepted"):
    return BoundaryReviewResponse({"findings": [{"finding_id": "f1", "status": status, "rationale": "Rule and inspected import agree.",
                           "severity": "medium", "confidence": 0.8}], "limitations": []})


def hypothesis_review():
    response = review()
    response["findings"] = []
    return response


def audit(repo, responses, **config):
    tools = toolset(repo)
    model = ScriptedModel(responses)
    agent = ArchitectureBoundaryAgent(model, BoundaryConfig(**({"max_total_tokens": 300_000} | config)))
    return asyncio.run(agent.run(tools, request())), model, tools


def fingerprints(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}
