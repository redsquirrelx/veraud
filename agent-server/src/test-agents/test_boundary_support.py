"""Boundary scope checks reject provenance-valid but substantively empty support."""

import json
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from test_architecture_boundary import PLAN, audit, call, evaluation, review

from server.agents.maintainability.modularity.architecture_boundary.support import (
    supports_role,
)

pytest_plugins = ["test_architecture_boundary"]


def test_repeated_large_typescript_role_checks_do_not_crash_native_parser():
    # A native access violation must fail a child process rather than kill pytest.
    script = textwrap.dedent('''
        import gc
        from types import SimpleNamespace
        from server.agents.maintainability.modularity.architecture_boundary.support import supports_role

        content = "\\n".join(
            f"export const item{i} = {{items: [{{name: 'item', data: load({i})}}]}};"
            for i in range(1500)
        )
        roles = ("declaration", "dependency", "implementation", "usage", "composition")
        for suffix in ("ts", "tsx", "js"):
            source = SimpleNamespace(path="large." + suffix, content=content)
            # Force complete traversal, then check a real observation on the last line.
            missing = SimpleNamespace(kind="source", start_line=1501, end_line=1501)
            present = SimpleNamespace(kind="source", start_line=1500, end_line=1500)
            for _ in range(3):
                for role in roles:
                    assert supports_role(source, missing, role) is False
                    assert supports_role(source, present, role) is True
        # The production crash surfaced during later Pydantic validation, when GC
        # traversed state corrupted by temporary Point.row attribute access. The
        # ordinary traversal above alone did not reproduce it.
        gc.set_threshold(1, 1, 1)
        source = SimpleNamespace(path="gc.ts", content=(
            "export const item = {items: [{name: 1, data: load(2)}]};\\n" * 500))
        present = SimpleNamespace(kind="source", start_line=500, end_line=500)
        results = [(supports_role(source, present, role), gc.collect())
            for _ in range(100) for role in ("declaration", "usage", "dependency")]
        assert all(supported for supported, _ in results)
        print("completed")
    ''')
    result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script],
        check=False, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "completed" in result.stdout


@pytest.mark.parametrize(("path", "content", "start", "end", "role", "expected"), [
    ("pyproject.toml", '# deps are isolated in .venv\n', 1, 1, "declaration", False),
    ("pyproject.toml", '[project]\nname="service"\n', 1, 2, "declaration", True),
    ("module.py", '"""All calls are isolated."""\n', 1, 1, "implementation", False),
    ("module.py", 'def run():\n    # performs work\n    return execute()\n', 2, 2, "implementation", False),
    ("module.py", 'def run():\n    return execute()\n', 1, 2, "usage", True),
    ("ports.py", 'from typing import Protocol\nclass Port(Protocol):\n    def run(self): ...\n', 1, 3, "implementation", False),
    ("ports.py", 'from typing import Protocol\nclass Port(Protocol):\n    def run(self): ...\n', 1, 3, "declaration", True),
    ("module.ts", '// All dependencies use ports\nexport function run() { return execute(); }\n', 1, 1, "implementation", False),
    ("module.ts", '// All dependencies use ports\nexport function run() { return execute(); }\n', 2, 2, "usage", True),
])
def test_exact_cited_lines_must_contain_the_declared_role(path, content, start, end, role, expected):
    source = SimpleNamespace(path=path, content=content)
    ref = SimpleNamespace(kind="source", start_line=start, end_line=end)
    assert supports_role(source, ref, role) is expected


def test_comments_and_protocols_cannot_establish_system_isolation(repo):
    (repo / "ports.py").write_text("from typing import Protocol\nclass Port(Protocol):\n    def run(self): ...\n")

    def overclaim(messages):
        value = evaluation(messages)
        value["hypotheses"] = []
        value["candidates"][0].update(title="All dependencies are isolated", components=["ports.py"])
        ids = value["candidates"][0]["evidence_ids"]
        value["claim_checks"] = [{"subject_type": "candidate", "subject_id": "f1",
            "claim_kind": "isolation", "scope_paths": ["ports.py"], "coverage_complete": True,
            "support": [{"evidence_id": ids[0], "role": "declaration", "observation": "A Protocol is declared"}]}]
        return value

    result, _, _ = audit(repo, [{**PLAN, "hypotheses": []}, call(arguments={"path": "ports.py", "start_line": 1, "end_line": 3}),
        AIMessage(content="Ready"), overclaim, review()], max_iterations=1)
    assert result.termination_reason != "sufficient_evidence"
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "boundary_missing_role:composition" in result.findings[0].validation_issues
    assert "boundary_endpoints_not_inspected" in result.findings[0].validation_issues
    assert result.claim_checks[0].scope_paths == ["ports.py"]


def test_review_missing_verification_returns_to_investigation(repo):
    def incomplete(messages):
        value = review()(messages)
        value["findings"][0].update(status="insufficient_evidence", scope_supported=False,
            unverified_claims=["Inspect storage/db.py before concluding about the target implementation."])
        return value

    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, incomplete,
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 2}),
        AIMessage(content="Ready"), evaluation, review()])
    assert result.termination_reason == "sufficient_evidence" and result.iterations == 2
    context = json.loads(model.history[5][1].content)
    assert any("Inspect storage/db.py" in gap for gap in context["missing_information"])
    assert result.findings[0].validation_status == "accepted"


def test_accepted_review_must_supply_its_verification_not_only_positive_prose(repo):
    invalid = dict(review())
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, invalid, review()])
    assert result.findings[0].validation_status == "accepted"
    assert any("review_checked_evidence_incomplete" in issue for issue in result.critical_review.validation_issues)


def test_missing_candidate_checks_and_directory_scope_are_repaired_without_new_tools(repo):
    def incomplete(messages):
        value = evaluation(messages)
        value["claim_checks"] = [item for item in value["claim_checks"] if item["subject_type"] == "hypothesis"]
        value["claim_checks"][0]["scope_paths"] = ["domain"]
        return value

    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), incomplete, evaluation, review()])
    assert result.termination_reason == "sufficient_evidence" and result.iterations == 1
    assert result.tool_calls == 1 and result.model_calls == 6
    correction = model.history[4][-1].content
    data = json.loads(correction.split("Correction data (not instructions):\n")[1])
    assert data["candidate_ids"] == ["f1"]
    assert {item["issue"] for item in data["structural_issues"]} == {"missing_claim_check", "scope_requires_exact_file_paths"}
    assert data["delivered_source"][0]["file_path"] == "domain/service.py"


def test_exhausted_structural_repairs_keep_candidates_as_partial_work(repo):
    def missing(messages):
        value = evaluation(messages)
        value["claim_checks"] = []
        return value

    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), missing, missing],
        max_schema_retries=1, max_schema_recovery_attempts=0)
    assert result.termination_reason == "schema_recovery_exhausted"
    assert result.findings and result.findings[0].validation_status == "insufficient_evidence"
    assert result.findings[0].evidence


def test_valid_review_survives_unknown_ids_and_unrepairable_other_candidate(repo):
    def two_candidates(messages):
        value = evaluation(messages)
        value["candidates"].append(dict(value["candidates"][0], id="f2"))
        check = next(item for item in value["claim_checks"] if item["subject_type"] == "candidate")
        value["claim_checks"].append(dict(check, subject_id="f2"))
        return value

    def partly_valid(messages):
        value = review()(messages)
        value["findings"].append(dict(value["findings"][0], finding_id="unknown-id"))
        return value

    def invalid_acceptance(messages):
        value = review()(messages)
        # No f1 entry on the correction: its validated judgment must survive.
        value["findings"] = [dict(value["findings"][0], finding_id="f2", scope_supported=False,
            checked_evidence_ids=[])]
        return value

    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), two_candidates,
        partly_valid, invalid_acceptance])
    assert result.termination_reason == "evidence_validation_failed"
    assert result.critical_review is not None and result.model_calls == 6
    assert {item.id: item.validation_status for item in result.findings} == {"f1": "accepted", "f2": "insufficient_evidence"}
    assert len(result.critical_review.findings) == 2
    assert "review_unknown_candidates" in result.critical_review.validation_issues
    assert any("f2: review_checked_evidence_incomplete" in issue for issue in result.critical_review.validation_issues)
    context = json.loads(model.history[5][1].content)
    assert {item["candidate_id"] for item in context["boundary_review_requirements"]} == {"f1", "f2"}


@pytest.mark.parametrize("limited_calls", [False, True])
def test_failed_repair_preserves_valid_evaluation_and_spends_reserved_review_calls(repo, limited_calls):
    def valid_but_incomplete(messages):
        return evaluation(messages, sufficient=False)

    def invalid_replacement(messages):
        value = evaluation(messages)
        value["candidates"][0]["id"] = "unverified-replacement"
        value["claim_checks"] = []
        return value

    config = ({"max_model_calls": 10} if limited_calls else
        {"max_schema_retries": 0, "max_schema_recovery_attempts": 0})
    attempts = [invalid_replacement] * (2 if limited_calls else 1)
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), valid_but_incomplete,
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 2}),
        AIMessage(content="Ready"), *attempts, review()], **config)
    assert result.termination_reason == ("model_call_limit" if limited_calls else "schema_recovery_exhausted")
    assert result.critical_review is not None
    assert [finding.id for finding in result.findings] == ["f1"]
    assert result.failed_evaluation_attempt.candidates[0].id == "unverified-replacement"
    assert result.evaluation_attempt_issues
    assert result.tool_calls == 2 and result.iterations == 2
    assert result.model_calls == (9 if limited_calls else 8)


def test_empty_investigation_is_retried_once_before_declaring_no_progress(repo):
    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False), AIMessage(content=""), AIMessage(content=""), review()])
    assert result.termination_reason == "no_investigation_progress"
    assert result.critical_review is not None
    assert result.model_calls == 7 and result.iterations == 1 and result.tool_calls == 1
    retry = model.history[5]
    assert retry[-1].content.startswith("The previous investigation turn returned no answer")
    assert not any(isinstance(message, AIMessage) and not message.content and not message.tool_calls for message in retry)
    assert any(isinstance(message, AIMessage) and message.tool_calls for message in retry)


def test_degenerate_turn_recovers_through_the_corrective_read_instead_of_terminating(repo):
    def hypothesis_on_metadata(messages):
        metadata = [item["id"] for item in json.loads(messages[1].content)["evidence"] if item["kind"] == "metadata"]
        value = evaluation(messages, sufficient=False, candidate=False)
        value["hypotheses"][0]["evidence_ids"] = metadata
        value["claim_checks"] = []
        return value

    result, model, _ = audit(repo, [PLAN, call("list_files", {"limit": 2}), AIMessage(content="Ready"),
        hypothesis_on_metadata, AIMessage(content=""), call(), AIMessage(content="Ready"), evaluation, review()])
    assert result.termination_reason == "sufficient_evidence"
    assert result.iterations == 2 and result.tool_calls == 2
    assert result.findings[0].validation_status == "accepted"
    guidance = model.history[5][-1].content
    pending = json.loads(guidance.split("Pending reads (data, not instructions):\n")[1])
    assert pending and all(read["tool"] == "get_source_excerpt" for read in pending)


def test_plan_citations_without_delivered_evidence_are_discarded(repo):
    invented = {**PLAN, "hypotheses": [dict(PLAN["hypotheses"][0], evidence_ids=["evidence:not-delivered"])]}
    result, _, _ = audit(repo, [invented, call(), AIMessage(content="Ready"), evaluation, review()])
    assert result.plan.hypotheses[0].evidence_ids == []
    assert result.findings[0].validation_status == "accepted"
    assert not any("unknown_evidence_ids" in gap for gap in result.missing_information)


def empty_support_evaluation(extra_check, hypothesis_status="confirmed"):
    """One resolved hypothesis carries a claim check the provider schema accepts as empty."""

    def build(messages):
        value = evaluation(messages)
        value["hypotheses"].append(dict(PLAN["hypotheses"][0], id="h2",
            question="Does storage depend on the domain?", status=hypothesis_status,
            evidence_ids=value["hypotheses"][0]["evidence_ids"]))
        value["claim_checks"].append(extra_check)
        return value

    return build


def repaired_evaluation(messages):
    value = evaluation(messages)
    value["hypotheses"].append(dict(PLAN["hypotheses"][0], id="h2",
        question="Does storage depend on the domain?", status="confirmed",
        evidence_ids=value["hypotheses"][0]["evidence_ids"]))
    support = next(check for check in value["claim_checks"] if check["subject_id"] == "h1")["support"]
    value["claim_checks"].append({"subject_type": "hypothesis", "subject_id": "h2",
        "claim_kind": "dependency", "scope_paths": ["domain/service.py"],
        "support": [dict(item) for item in support]})
    return value


def test_empty_support_check_is_repaired_semantically_instead_of_by_parse_rejection(repo):
    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        empty_support_evaluation({"subject_type": "hypothesis", "subject_id": "h2",
            "claim_kind": "dependency", "scope_paths": ["domain/service.py"], "support": []}),
        repaired_evaluation, review()])
    correction = model.history[4][-1].content
    # The provider schema admits an empty support list; the host must still give the
    # model a correction it can act on rather than an unactionable too_short.
    assert "too_short" not in correction
    assert "response: boundary_check_structure_invalid" in correction
    data = json.loads(correction.split("Correction data (not instructions):\n")[1])
    assert data["structural_issues"] == [{"subject_type": "hypothesis", "subject_id": "h2",
        "issue": "missing_claim_check"}]
    assert "h2" in data["resolved_hypothesis_ids"]
    assert result.termination_reason == "sufficient_evidence" and result.iterations == 1
    assert result.hypotheses[1].status == "confirmed"
    assert result.model_calls == 6 and result.tool_calls == 1


def test_candidate_with_empty_collections_gets_precise_feedback_not_generic_schema_advice(repo):
    def empty_candidate(messages):
        value = evaluation(messages, candidate=False)
        value["candidates"] = [{"id": "f1", "title": "Domain imports storage", "description": "Direct dependency",
            "criterion_id": "domain-rule", "kind": "violation", "components": [], "evidence_ids": [],
            "justification": "j", "modularity_impact": "m", "severity": "medium",
            "confidence": 0.5, "recommendation": "r"}]
        return value

    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), empty_candidate,
        evaluation, review()])
    correction = model.history[4][-1].content
    assert "candidates.0.components: too_short" in correction
    assert "An empty list is not a placeholder" in correction
    assert "Follow every field, type, enum and constraint in the response schema" not in correction
    assert result.termination_reason == "sufficient_evidence"
    assert result.findings[0].validation_status == "accepted"


def review_of_hypotheses(messages):
    """The model judges hypotheses instead of the candidate under review."""
    value = review()(messages)
    value["findings"] = [dict(value["findings"][0], finding_id="h1")]
    return value


def test_unresolvable_citation_still_receives_readable_navigation(repo):
    """A hypothesis citing only unknown ids must not get an empty, unactionable task."""
    def invented(messages):
        value = evaluation(messages, candidate=False, sufficient=False)
        value["hypotheses"][0]["evidence_ids"] = ["evidence:never-delivered"]
        value["hypotheses"][0]["evidence_needed"] = ["Read storage/db.py implementation"]
        value["claim_checks"] = []
        return value

    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), invented, review()],
        max_iterations=1)
    context = json.loads(model.history[4][1].content)
    task = next(item for item in context["evidence_recovery_tasks"] if item["id"] == "h1")
    assert task["cited_paths"] == [] and task["available_source_evidence_ids"] == []
    assert task["navigation_scope_paths"] == ["storage", "domain"]  # named by the subject itself
    # storage/db.py was never read; domain/service.py already was and is not re-suggested.
    assert [read["arguments"]["path"] for read in task["next_source_reads"]] == ["storage/db.py"]
    assert all(read["navigation_only"] for read in task["next_source_reads"])
    assert result.tool_calls == 1  # navigation hints are never executed as evidence


def test_isolation_gap_suggests_unread_endpoints_outside_the_declared_scope(repo):
    (repo / "app").mkdir()
    (repo / "app" / "route.ts").write_text(
        'import { save } from "../storage/db";\n\nexport function handler() {\n  return save();\n}\n')
    (repo / "storage" / "db.ts").write_text("export function save() {\n  return null;\n}\n")

    def endpoint_claim(messages):
        value = evaluation(messages)
        context = json.loads(messages[1].content)
        endpoint = next(item["id"] for item in context["evidence"] if item["path"] == "storage/db.ts")
        for check in value["claim_checks"]:
            if check["subject_type"] == "hypothesis":
                check.update(claim_kind="isolation", scope_paths=["storage/db.ts"],
                    support=[{"evidence_id": endpoint, "role": "implementation",
                        "observation": "Persists through the declared boundary"}])
        return value

    result, model, _ = audit(repo, [PLAN, call(),
        call(arguments={"path": "storage/db.ts", "start_line": 1, "end_line": 2}, identifier="call-2"),
        AIMessage(content="Ready"), endpoint_claim, review()], max_iterations=1)
    assert result.hypotheses[0].status == "inconclusive"
    assert "boundary_endpoints_not_inspected" in result.hypotheses[0].rationale
    context = json.loads(model.history[5][1].content)
    task = next(item for item in context["evidence_recovery_tasks"] if item["id"] == "h1")
    endpoints = task["endpoint_source_reads"]
    assert endpoints and endpoints[0]["arguments"]["path"] == "app/route.ts"
    assert set(endpoints[0]["potential_roles"]) & {"usage", "composition"}
    assert all(read["navigation_only"] for read in endpoints)
    # Navigation must never silently widen the declared scope of the claim.
    assert result.claim_checks[0].scope_paths == ["storage/db.ts"]
    assert result.tool_calls == 2


def test_rejection_names_the_claim_kinds_the_same_evidence_would_pass(repo):
    """Six runs produced no finding because isolation was chosen over the support given.

    The same inspected range carries a declaration, a dependency and an implemented
    behavior; only the isolation bar rejects it. The repair must say so.
    """
    def overreaching(messages):
        value = evaluation(messages)
        for check in value["claim_checks"]:
            check.update(claim_kind="isolation", coverage_complete=True,
                support=[dict(item, role="dependency") for item in check["support"]])
        return value

    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), overreaching, review()],
        max_iterations=1)
    context = json.loads(model.history[4][1].content)
    task = next(item for item in context["evidence_recovery_tasks"] if item["id"] == "h1")
    assert task["issues"] == ["boundary_missing_role:composition", "boundary_missing_role:implementation",
        "boundary_missing_role:usage", "boundary_endpoints_not_inspected",
        "boundary_related_endpoints_not_supported"]
    assert task["satisfiable_claim_kinds"] == ["declaration", "behavior", "dependency"]
    assert task["action"] == "narrow_claim_kind_or_inspect_missing_roles"
    assert any("The inspected support carries these claim kinds: declaration, behavior, dependency"
        in gap for gap in result.missing_information)


def test_unsatisfiable_claim_is_not_presented_as_a_choice(repo):
    """Support that cannot cover the declared scope offers no narrower alternative."""
    def impossible(messages):
        value = evaluation(messages, candidate=False)
        value["claim_checks"] = [{"subject_type": "hypothesis", "subject_id": "h1",
            "claim_kind": "dependency", "scope_paths": ["storage/db.py"],
            "support": [{"evidence_id": check_id(messages), "role": "dependency",
                "observation": "Imports the storage module"}]}]
        return value

    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), impossible, review()],
        max_iterations=1)
    context = json.loads(model.history[4][1].content)
    task = next(item for item in context["evidence_recovery_tasks"] if item["id"] == "h1")
    assert task["issues"] == ["boundary_support_outside_declared_scope", "boundary_scope_not_inspected"]
    assert "satisfiable_claim_kinds" not in task
    assert not any("The inspected support carries" in gap for gap in result.missing_information)
    assert result.hypotheses[0].status == "inconclusive"


def check_id(messages):
    return json.loads(messages[1].content)["evidence"][0]["id"]


def test_retrieved_evidence_survives_a_run_without_any_evaluation(repo):
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), RuntimeError("provider unavailable")])
    assert result.termination_reason == "model_or_schema_error"
    assert result.claim_checks == [] and result.findings == []
    assert "A valid evidence evaluation could not be completed." in result.missing_information
    # One real file was read; a failed evaluation must not erase the audited bytes.
    assert [item.path for item in result.evidence] == ["domain/service.py"]
    assert result.evidence[0].kind == "source" and result.evidence[0].content_hash
    assert result.evidence[0].path == "domain/service.py" and result.evidence[0].start_line == 1
    # This fixture has no commit, so attribution stays snapshot-only; committed checkouts
    # are covered by the commit-attribution tests.


@pytest.fixture
def layered_repo(repo):
    """A second subsystem, so a question can name one path and be answered from another."""
    (repo / "app" / "api").mkdir(parents=True)
    (repo / "app" / "api" / "route.py").write_text("def handler():\n    return save()\n")
    return repo


def test_hypothesis_cannot_be_answered_with_evidence_from_another_subsystem(layered_repo):
    def substituted(messages):
        value = evaluation(messages)
        value["hypotheses"][0].update(
            question="Is the 'app/api' layer acting as a thin translation proxy?",
            evidence_needed=["Read app/api/route.py"])
        return value

    result, _, _ = audit(layered_repo, [PLAN, call(), AIMessage(content="Ready"),
        substituted, review()], max_iterations=1)
    # The cited implementation satisfies its own role and is self-consistent, which is
    # exactly why roles and scope alone cannot detect a substitution.
    assert result.claim_checks[0].scope_paths == ["domain/service.py"]
    assert result.hypotheses[0].status == "inconclusive"
    assert "boundary_scope_unrelated_to_subject" in result.hypotheses[0].rationale
    assert any("shares nothing with what this question names" in gap for gap in result.missing_information)


def test_hypothesis_scope_matching_what_it_names_is_still_accepted(layered_repo):
    def on_scope(messages):
        value = evaluation(messages)
        value["hypotheses"][0].update(question="Is the 'domain' module dependent on storage?",
            evidence_needed=["Read domain/service.py"])
        return value

    result, _, _ = audit(layered_repo, [PLAN, call(), AIMessage(content="Ready"),
        on_scope, review()], max_iterations=1)
    assert result.hypotheses[0].status == "confirmed"
    assert "boundary_scope_unrelated_to_subject" not in result.hypotheses[0].rationale
    assert result.termination_reason == "sufficient_evidence"


def test_hypothesis_naming_no_inspectable_scope_is_not_judged_on_relevance(repo):
    def abstract(messages):
        value = evaluation(messages)
        value["hypotheses"][0].update(
            question="Does the persistence boundary allow independent replacement?",
            evidence_needed=["Inspect the persistence contract"])
        return value

    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), abstract, review()],
        max_iterations=1)
    assert result.hypotheses[0].status == "confirmed"
    assert result.termination_reason == "sufficient_evidence"


def test_review_judging_the_wrong_subjects_is_repaired_once_not_discarded(repo):
    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation,
        review_of_hypotheses, review()])
    correction = json.loads(model.history[5][1].content)
    assert {item["candidate_id"] for item in correction["boundary_review_requirements"]} == {"f1"}
    prior = correction["prior_critical_review"]
    assert "review_unknown_candidates" in prior["validation_issues"]
    # The stray judgment is dropped from the retained review; only real candidates survive.
    assert [item["finding_id"] for item in prior["findings"]] == ["f1"]
    # A support issue must not suppress a repairable metadata defect.
    assert "review_unknown_candidates" in result.critical_review.validation_issues
    assert result.findings[0].validation_status == "accepted"
    assert result.termination_reason == "sufficient_evidence" and result.model_calls == 6


def test_absent_candidate_judgment_is_not_reported_as_no_review_supplied(repo):
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation,
        review_of_hypotheses, review_of_hypotheses], max_schema_retries=0)
    judgment = next(item for item in result.critical_review.findings if item.finding_id == "f1")
    assert "the review answered other subjects" in judgment.rationale
    assert "No review was supplied" not in judgment.rationale
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_review_of_a_candidate_free_evaluation_does_not_claim_unknown_candidates(repo):
    def invented_judgment(messages):
        value = review()(messages)
        value["findings"].append(dict(value["findings"][0], finding_id="not-a-candidate"))
        return value

    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, candidate=False), invented_judgment])
    assert result.findings == []
    assert result.claim_checks[0].subject_type == "hypothesis"
    assert "review_unknown_candidates" not in result.critical_review.validation_issues
    assert "review_judgments_without_candidates" in result.critical_review.validation_issues


def test_role_recovery_suggests_unread_implementation_ranges_not_more_headers(repo):
    (repo / "domain" / "service.py").write_text('"""Architectural guarantees are declarations only."""\n\ndef execute():\n    return save()\n')
    def header_claim(messages):
        value = evaluation(messages)
        for check in value["claim_checks"]:
            check["claim_kind"] = "behavior"
            for support in check["support"]:
                support["role"] = "implementation"
        return value

    result, model, _ = audit(repo, [PLAN, call(arguments={"path": "domain/service.py", "start_line": 1, "end_line": 1}),
        AIMessage(content="Ready"), header_claim, review()], max_iterations=1)
    assert result.findings[0].validation_status == "insufficient_evidence"
    context = json.loads(model.history[4][1].content)
    reads = [read for task in context["evidence_recovery_tasks"] for read in task.get("next_source_reads", [])]
    assert reads and reads[0]["arguments"]["start_line"] == 3
    assert all(read["navigation_only"] for read in reads)
    assert result.tool_calls == 1  # suggestions are not fabricated tool executions/evidence
