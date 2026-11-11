"""Documentary normalization and bounded abstraction planning."""

from types import SimpleNamespace

import pytest
from pydantic_core import PydanticCustomError

from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.config import (
    AbstractionConfig,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.execution import (
    AbstractionExecution,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.planning import (
    build_abstraction_plan,
    normalize_knowledge,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.schemas import (
    AbstractionPlanSelection,
    AbstractionRequest,
)


def claim(**changes):
    return {
        "category": "components",
        "subject": "payment processor",
        "statement": "PaymentProcessor coordinates gateway calls.",
        "related_subjects": ["gateway"],
        "certainty": "explicit",
        "section_ids": ["section-1"],
        "reasoning": "The architecture document names this responsibility.",
        "constraint": "unspecified",
        "evidence": [{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "PaymentProcessor"}],
    } | changes


def context(**changes):
    return {
        "schema_version": "1",
        "document_index": {"index_id": "index-sha", "repository_id": "repo", "commit": "a" * 40},
        "knowledge": [claim(), claim(subject="gateway", statement="Gateway abstracts vendor APIs.")],
        "knowledge_issues": [],
        "covered_categories": [],
        "pending_categories": [],
        "evaluated_categories": [],
        "coverage_assessment_status": "not_run",
        "consulted_documents": [],
        "section_paths": {"section-1": "docs/architecture.md"},
        "validation_errors": [],
        "execution_status": "partial",
        "finalization_reason": "test",
    } | changes


def documentary(**overrides):
    return ArchitectureContextResult.model_validate(context(**overrides))


def test_normalize_knowledge_assigns_positional_ids_and_preserves_documentary_fields():
    records = normalize_knowledge(context())
    assert [record["id"] for record in records] == ["claim-0", "claim-1"]
    assert records[0]["id"] == "claim-0"
    assert records[0]["category"] == "components"
    assert records[0]["subject"] == "payment processor"
    assert records[0]["statement"] == "PaymentProcessor coordinates gateway calls."
    assert records[0]["related_subjects"] == ["gateway"]
    assert records[0]["certainty"] == "explicit"
    assert records[0]["constraint"] == "unspecified"
    assert records[0]["section_ids"] == ["section-1"]
    assert records[0]["evidence"] == [{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "PaymentProcessor"}]
    assert records[0]["document_index"] == {"index_id": "index-sha", "repository_id": "repo", "commit": "a" * 40}
    assert records[0]["section_paths"] == {"section-1": "docs/architecture.md"}
    assert "reasoning" not in records[0]


def test_normalize_knowledge_accepts_the_typed_architecture_context():
    typed = documentary()
    assert normalize_knowledge(typed)[0]["id"] == "claim-0"


def test_normalize_knowledge_returns_empty_for_missing_or_empty_documented_context():
    assert normalize_knowledge(None) == []
    assert normalize_knowledge(context(knowledge=[])) == []


def test_normalize_knowledge_degrades_without_a_documentary_index_id():
    records = normalize_knowledge(context(document_index=None))
    assert records[0]["id"] == "claim-0"
    assert records[0]["document_index"] is None


def test_normalize_knowledge_validates_claims_before_assigning_ids():
    invalid = context(knowledge=[claim(section_ids=[])])
    with pytest.raises(ValueError):
        normalize_knowledge(invalid)


# --- bounded planning ---------------------------------------------------------

def _file(identifier, path, module_name=None, language="python"):
    return SimpleNamespace(id=identifier, path=path, module_name=module_name, project_id="p",
        language=language, size_bytes=1, status="processed")


def _symbol(identifier, file_id, kind, name, *, qualified_name=None, base_names=(), start_line=1, end_line=2):
    return SimpleNamespace(id=identifier, file_id=file_id, kind=kind, name=name,
        qualified_name=qualified_name or name, base_names=tuple(base_names),
        start_line=start_line, end_line=end_line, signature=None, decorators=(), evidence_ids=())


def _relation(source_id, target_id, resolution="internal"):
    return SimpleNamespace(id=f"{source_id}:{target_id}", source_id=source_id,
        target_id=target_id, kind="import", resolution=resolution, specifier="", evidence_ids=())


def _snapshot(files, symbols, relationships=(), hash="abc"):
    return SimpleNamespace(files=list(files), symbols=list(symbols), relationships=list(relationships),
        testing=[], coverage=SimpleNamespace(unsupported_source_languages=[], issues=[]),
        repository=SimpleNamespace(snapshot_hash=hash), projects=[], entrypoints=[])


def _plan(snapshot, request=None, *, max_investigations=8):
    return build_abstraction_plan(snapshot, request or AbstractionRequest(),
        check=lambda: None, max_investigations=max_investigations)


def _executing(plan, *, max_planned_investigations=4):
    execution = object.__new__(AbstractionExecution)
    execution._menu = list(plan.candidates)
    execution._planning_context = {}
    execution.config = AbstractionConfig(max_planned_investigations=max_planned_investigations)
    return execution


def test_interfaces_and_protocols_are_discovered():
    files = [_file("f0", "src/payments.py", "src.payments"),
        _file("f1", "src/gateways.py", "src.gateways")]
    symbols = [
        _symbol("s0", "f0", "interface", "PaymentGateway"),
        _symbol("s1", "f0", "class", "ProviderProtocol", base_names=("Protocol",)),
        _symbol("s2", "f0", "class", "RegularClass"),
        _symbol("s3", "f1", "class", "StripeGateway", base_names=("PaymentGateway",)),
        _symbol("s4", "f1", "class", "FakeProtocol", base_names=("ProviderProtocol",))]

    plan = _plan(_snapshot(files, symbols))

    names = {(c.abstraction_name, c.abstraction_kind) for c in plan.candidates}
    assert ("PaymentGateway", "interface") in names
    assert ("ProviderProtocol", "protocol") in names
    assert ("RegularClass", "class") not in names


def test_documented_helper_create_api_handler_is_discovered():
    files = [_file("f0", "api/handler.py", "api.handler")]
    symbols = [_symbol("s0", "f0", "function", "createApiHandler")]
    document = documentary(knowledge=[claim(category="architectural_decisions",
        subject="createApiHandler",
        statement="createApiHandler abstracts the public HTTP handler contract.",
        related_subjects=[],
        evidence=[{"section_id": "section-1", "start_line": 2, "end_line": 4,
            "quote": "createApiHandler"}])])

    plan = _plan(_snapshot(files, symbols), AbstractionRequest(documented_architecture=document))

    assert [candidate.abstraction_name for candidate in plan.candidates] == ["createApiHandler"]
    candidate = plan.candidates[0]
    assert candidate.abstraction_kind == "documented_helper"
    assert candidate.documented_purpose == "createApiHandler abstracts the public HTTP handler contract."
    assert candidate.purpose_basis == "explicit"
    assert candidate.document_claim_ids == ["claim-0"]


def test_subject_matching_normalizes_case_spacing_and_punctuation():
    files, symbols, relationships = _llm_provider_snapshot()
    for subject in ["LlmProvider", "LLM Provider", "llm_provider", "llm-provider", "LLMPROVIDER"]:
        document = context(knowledge=[claim(category="interfaces_and_contracts", subject=subject,
            statement="LlmProvider is the contract every LLM backend implements; consumers depend on it.",
            related_subjects=[],
            evidence=[{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "LlmProvider"}])])

        plan = _plan(_snapshot(files, symbols, relationships),
            AbstractionRequest(documented_architecture=documentary(**document)))

        provider = next(candidate for candidate in plan.candidates
            if candidate.abstraction_name == "LlmProvider")
        assert provider.document_claim_ids == ["claim-0"], subject


def test_subject_matching_accepts_exact_qualified_name_reference():
    files = [_file("f0", "src/llm/provider.py", "src.llm.provider")]
    symbols = [_symbol("s0", "f0", "class", "LlmProvider",
        qualified_name="src.llm.provider.LlmProvider", base_names=("Protocol",))]
    document = context(knowledge=[claim(category="interfaces_and_contracts",
        subject="src.llm.provider.LlmProvider",
        statement="The qualified contract is LlmProvider.",
        related_subjects=[],
        evidence=[{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "LlmProvider"}])])

    plan = _plan(_snapshot(files, symbols), AbstractionRequest(documented_architecture=documentary(**document)))

    assert [candidate.abstraction_name for candidate in plan.candidates] == ["LlmProvider"]
    assert plan.candidates[0].document_claim_ids == ["claim-0"]


def test_data_contract_retrocompatibility_is_preserved_not_turned_into_interchangeability():
    files = [_file("f0", "src/session.py", "src.session")]
    symbols = [_symbol("s0", "f0", "type_alias", "SessionPayload")]
    document = context(knowledge=[claim(category="constraints", subject="SessionPayload",
        statement="SessionPayload must remain backward compatible; existing fields MUST NOT be removed.",
        related_subjects=[],
        evidence=[{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "SessionPayload"}])])

    plan = _plan(_snapshot(files, symbols), AbstractionRequest(documented_architecture=documentary(**document)))

    payload = plan.candidates[0]
    assert payload.abstraction_kind == "type_alias"
    assert payload.document_claim_ids == ["claim-0"]
    assert "backward compatible" in (payload.documented_purpose or "")


def _llm_provider_snapshot():
    files = [_file("f0", "src/llm/provider.py", "src.llm.provider"),
        _file("f1", "src/llm/gemini.py", "src.llm.gemini"),
        _file("f2", "src/app/gateway.py", "src.app.gateway")]
    symbols = [
        _symbol("s0", "f0", "class", "LlmProvider", base_names=("Protocol",)),
        _symbol("s1", "f1", "class", "GeminiProvider", base_names=("LlmProvider",)),
        _symbol("s2", "f2", "class", "Gateway")]
    relationships = [_relation("f2", "f0"), _relation("f1", "f0")]
    return files, symbols, relationships


def _llm_provider_document():
    return context(knowledge=[
        claim(category="interfaces_and_contracts", subject="LlmProvider",
            statement="LlmProvider is the contract every LLM backend implements.",
            related_subjects=[],
            evidence=[{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "LlmProvider"}]),
        claim(category="architectural_decisions", subject="LlmProvider",
            statement="The project abstracts model transport behind LlmProvider.",
            related_subjects=[],
            evidence=[{"section_id": "section-1", "start_line": 10, "end_line": 12, "quote": "LlmProvider"}]),
    ])


def test_llm_provider_is_documented_with_decisions_and_contracts():
    files, symbols, relationships = _llm_provider_snapshot()

    plan = _plan(_snapshot(files, symbols, relationships),
        AbstractionRequest(documented_architecture=documentary(**_llm_provider_document())))

    assert [candidate.abstraction_name for candidate in plan.candidates] == ["LlmProvider"]
    candidate = plan.candidates[0]
    assert candidate.abstraction_kind == "protocol"
    assert candidate.purpose_basis == "explicit"
    assert candidate.document_claim_ids == ["claim-0", "claim-1"]
    assert set(candidate.related_components) <= {"src/llm/gemini.py", "src/app/gateway.py"}
    assert candidate.priority == "high"
    assert set(plan.document_claims) == {"claim-0", "claim-1"}
    assert plan.document_claims["claim-0"].claim.evidence[0].quote == "LlmProvider"
    assert plan.document_claims["claim-0"].status == "applicable"
    assert plan.document_claims["claim-0"].scope_paths == ["src/llm/provider.py"]


def test_irrelevant_claims_are_excluded_from_candidate_selection():
    files, symbols, relationships = _llm_provider_snapshot()
    document = context(knowledge=[
        claim(category="responsibilities", subject="LlmProvider",
            statement="test fixtures use LlmProvider with pytest fixtures."),
        claim(category="architectural_decisions", subject="Gateway",
            statement="Gateway is checked through vitest coverage."),
    ])

    plan = _plan(_snapshot(files, symbols, relationships),
        AbstractionRequest(documented_architecture=documentary(**document)))

    assert all(not candidate.document_claim_ids for candidate in plan.candidates)
    assert plan.document_claims == {}


def test_component_claim_does_not_misattribute_responsibilities_to_abstractions():
    files = [_file("f0", "src/auth.py", "src.auth"),
        _file("f1", "src/login.py", "src.login"),
        _file("f2", "src/profile.py", "src.profile")]
    symbols = [
        _symbol("s0", "f0", "class", "AuthManager", base_names=("Protocol",)),
        _symbol("s1", "f0", "class", "UserProfileResult", base_names=("Protocol",)),
        _symbol("s2", "f1", "class", "LoginManager", base_names=("AuthManager",)),
        _symbol("s3", "f2", "class", "ProfileClaim", base_names=("UserProfileResult",))]
    document = context(knowledge=[
        claim(category="interfaces_and_contracts", subject="AuthManager",
            statement="AuthManager issues and verifies session tokens.",
            related_subjects=["UserProfileResult"],
            evidence=[{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "AuthManager"}]),
        claim(category="components", subject="src.auth",
            statement="The auth service issues and verifies session tokens for every request.",
            related_subjects=[],
            evidence=[{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "auth service"}])])

    plan = _plan(_snapshot(files, symbols), AbstractionRequest(documented_architecture=documentary(**document)))

    by_name = {candidate.abstraction_name: candidate for candidate in plan.candidates}
    assert by_name["AuthManager"].document_claim_ids == ["claim-0"]
    assert by_name["AuthManager"].purpose_basis == "explicit"
    assert "AuthManager issues and verifies session tokens." in by_name["AuthManager"].documented_purpose
    assert by_name["UserProfileResult"].document_claim_ids == []
    assert by_name["UserProfileResult"].documented_purpose is None
    assert any("not attributable" in item for item in plan.limitations)


def test_related_references_without_a_single_owner_are_ambiguous():
    files = [_file("f0", "src/auth.py", "src.auth"),
        _file("f1", "src/llm.py", "src.llm"),
        _file("f2", "src/gateway.py", "src.gateway"),
        _file("f3", "src/impl.py", "src.impl")]
    symbols = [
        _symbol("s0", "f0", "class", "AuthManager", base_names=("Protocol",)),
        _symbol("s1", "f1", "class", "LlmProvider", base_names=("Protocol",)),
        _symbol("s2", "f2", "class", "GatewayAdapter", base_names=("Protocol",)),
        _symbol("s3", "f3", "class", "GeminiProvider", base_names=("LlmProvider",)),
        _symbol("s4", "f2", "class", "VendorGateway", base_names=("GatewayAdapter",))]
    document = context(knowledge=[
        claim(category="components", subject="Orchestrator",
            statement="Orchestrator coordinates AuthManager work and related gateways.",
            related_subjects=["AuthManager", "LlmProvider"],
            evidence=[{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "Orchestrator"}])])

    plan = _plan(_snapshot(files, symbols), AbstractionRequest(documented_architecture=documentary(**document)))

    assert plan.candidates
    assert all(not candidate.document_claim_ids for candidate in plan.candidates)
    assert any("ambiguous" in item for item in plan.limitations)


def test_ambiguous_correspondence_does_not_invent_a_component():
    files = [_file("f0", "src/a/llm.py", "src.a.llm"),
        _file("f1", "src/b/llm.py", "src.b.llm"),
        _file("f2", "src/a/impl.py", "src.a.impl"),
        _file("f3", "src/b/impl.py", "src.b.impl")]
    symbols = [
        _symbol("s0", "f0", "interface", "LlmProvider"),
        _symbol("s1", "f1", "interface", "LlmProvider"),
        _symbol("s2", "f2", "class", "ImplA", base_names=("LlmProvider",)),
        _symbol("s3", "f3", "class", "ImplB", base_names=("LlmProvider",))]
    document = context(knowledge=[claim(subject="LlmProvider", related_subjects=[],
        statement="LlmProvider is the LLM contract.")])

    plan = _plan(_snapshot(files, symbols),
        AbstractionRequest(documented_architecture=documentary(**document)))

    assert plan.candidates
    assert all(not candidate.document_claim_ids for candidate in plan.candidates)
    assert any("ambiguous" in item for item in plan.limitations)


def test_structural_candidate_without_documentation_gets_no_invented_purpose():
    files = [_file("f0", "src/payments.py", "src.payments"),
        _file("f1", "src/gateway.py", "src.gateway")]
    symbols = [_symbol("s0", "f0", "class", "PaymentGateway", base_names=("Protocol",)),
        _symbol("s1", "f1", "class", "StripGateway", base_names=("PaymentGateway",))]

    plan = _plan(_snapshot(files, symbols))

    assert [candidate.abstraction_name for candidate in plan.candidates] == ["PaymentGateway"]
    candidate = plan.candidates[0]
    assert candidate.purpose_basis == "unknown"
    assert candidate.documented_purpose is None
    assert candidate.priority in {"low", "medium"}
    assert "purpose" in candidate.question.lower()


def test_max_investigations_is_respected():
    files = [_file(f"f{i}", f"src/a{i}.py", f"src.a{i}") for i in range(5)] + [
        _file(f"g{i}", f"src/impl{i}.py", f"src.impl{i}") for i in range(5)]
    symbols = []
    for i in range(5):
        symbols.append(_symbol(f"s{i}", f"f{i}", "class", f"Abstraction{i}", base_names=("Protocol",)))
        symbols.append(_symbol(f"t{i}", f"g{i}", "class", f"Implementation{i}", base_names=(f"Abstraction{i}",)))

    plan = _plan(_snapshot(files, symbols), max_investigations=2)

    assert len(plan.candidates) == 2


def test_plan_contains_documentary_traceability_for_selected_candidates():
    files, symbols, relationships = _llm_provider_snapshot()

    plan = _plan(_snapshot(files, symbols, relationships),
        AbstractionRequest(documented_architecture=documentary(**_llm_provider_document())))

    assert set(plan.document_claims) == {"claim-0", "claim-1"}
    for claim_id, reference in plan.document_claims.items():
        assert claim_id.startswith("claim-")
        assert reference.claim.evidence and reference.claim.section_ids == ["section-1"]
        assert reference.section_paths == {"section-1": "docs/architecture.md"}
    for candidate in plan.candidates:
        assert set(candidate.document_claim_ids) <= set(plan.document_claims)


def test_empty_plan_is_valid():
    plan = _plan(_snapshot([_file("f0", "app.py", "app")],
        [_symbol("s0", "f0", "function", "main")]))

    assert plan.candidates == []
    assert plan.hypotheses == []
    assert any("empty plan is valid" in item for item in plan.limitations)


def test_selection_validation_rejects_unknown_or_duplicate_candidate_ids():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)
    assert plan.candidates, "expected a candidate in the provider fixture"

    with pytest.raises(PydanticCustomError) as unknown:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=["nope"], questions={}), {})
    assert unknown.value.type == "planning_unknown_candidate"

    with pytest.raises(PydanticCustomError) as duplicated:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[plan.candidates[0].id, plan.candidates[0].id],
                questions={plan.candidates[0].id: f"Why is {plan.candidates[0].primary_component} an abstraction?"}), {})
    assert duplicated.value.type == "planning_unknown_candidate"


def test_selection_validation_rejects_questions_without_primary_component():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)

    with pytest.raises(PydanticCustomError) as invalid:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[plan.candidates[0].id], questions={
                plan.candidates[0].id: "Too general?"}), {})
    assert invalid.value.type == "planning_invalid_question"


def test_selection_validation_rejects_too_many_candidates():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan, max_planned_investigations=1)
    candidate_id = plan.candidates[0].id

    with pytest.raises(PydanticCustomError) as too_many:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate_id, candidate_id], questions={}), {})
    assert too_many.value.type == "planning_size_limit"


def test_selection_validation_accepts_obligation_requirements():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)
    candidate = plan.candidates[0]

    AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
        AbstractionPlanSelection(candidate_ids=[candidate.id], questions={
            candidate.id: f"Does {candidate.primary_component} keep its contract substitutable?"},
            evidence_requirements={candidate.id: [
                "-  A drop-in implementation of LlmProvider ships without touching consumer code paths.",
                "Acceptance check: no constructor argument leaks the backing vendor beyond the LlmProvider contract shape."]}), {})

    assert execution._obligation_addenda == {candidate.id: [
        "A drop-in implementation of LlmProvider ships without touching consumer code paths.",
        "Acceptance check: no constructor argument leaks the backing vendor beyond the LlmProvider contract shape."]}


def test_selection_validation_rejects_obligation_requirements_for_unknown_candidates():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)

    candidate = plan.candidates[0]
    with pytest.raises(PydanticCustomError) as unknown:
        execution._plan_req_attempts = 0
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id],
                questions={candidate.id: f"Does {candidate.primary_component} hold up?"},
                evidence_requirements={"not-a-candidate": ["A drop-in implementation of LlmProvider ships"]}), {})
    assert unknown.value.type == "planning_requirements_unknown_candidate"


def test_selection_validation_rejects_malformed_obligation_requirements():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)
    candidate = plan.candidates[0]
    question = f"Does {candidate.primary_component} keep its contract substitutable?"

    with pytest.raises(PydanticCustomError) as empty:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id], questions={candidate.id: question},
                evidence_requirements={candidate.id: ["too short"]}), {})
    assert empty.value.type == "planning_requirements_invalid"

    with pytest.raises(PydanticCustomError) as too_many_items:
        execution._plan_req_attempts = 0
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id], questions={candidate.id: question},
                evidence_requirements={candidate.id: [
                    "A drop-in implementation of LlmProvider ships without touching consumer code paths.",
                    "The LlmProvider contract must stay thin so AnthropicProvider may drop in unmodified.",
                    "LlmProvider must not leak Gemini-specific configuration shapes or environment names.",
                    "A stub LlmProvider must pass the same consumer call sites unmodified.",
                    "LlmProvider must support a dual fan-out without leaking vendor identifiers anywhere in callers.",
                    "LlmProvider must credit the boundary with a redaction guard for every backend-specific error.",
                    "Extra LlmProvider obligation kept to trip the host's per-candidate bound on statements."]}), {})
    assert too_many_items.value.type == "planning_requirements_invalid"


def test_selection_validation_deduplicates_obligation_requirements():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)
    candidate = plan.candidates[0]

    AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
        AbstractionPlanSelection(candidate_ids=[candidate.id],
            questions={candidate.id: f"Does {candidate.primary_component} keep its contract substitutable?"},
            evidence_requirements={candidate.id: [
                "A drop-in implementation of LlmProvider ships without touching consumer code paths.",
                "a drop-in implementation of llmprovider ships without touching consumer code paths.",
                "An independent stub of LlmProvider must pass the same consumer call sites unmodified."]}), {})

    assert execution._obligation_addenda[candidate.id] == [
        "A drop-in implementation of LlmProvider ships without touching consumer code paths.",
        "An independent stub of LlmProvider must pass the same consumer call sites unmodified."]


def test_selection_validation_requires_obligations_for_every_selected_candidate():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)
    candidate = plan.candidates[0]

    with pytest.raises(PydanticCustomError) as missing:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id],
                questions={candidate.id: f"Does {candidate.primary_component} keep its contract substitutable?"},
                evidence_requirements={}), {})
    assert missing.value.type == "planning_requirements_invalid"

    with pytest.raises(PydanticCustomError) as single:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id],
                questions={candidate.id: f"Does {candidate.primary_component} keep its contract substitutable?"},
                evidence_requirements={candidate.id: [
                    "A drop-in implementation of LlmProvider ships without touching consumer code paths."]}), {})
    assert single.value.type == "planning_requirements_invalid"


def test_selection_validation_bounds_obligation_requirement_length():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)
    candidate = plan.candidates[0]

    long_requirement = (
        "LlmProvider obligations extend toward drop-in substitution for every consumer "
        "across the repository, enforce contract handling for each implementation the "
        "index can see, and forbid vendor-specific configuration shapes from leaking "
        "through any constructor signature or consumer code the caller interacts with, "
        "wherever the abstraction boundary is meant to prevail in practice today and in "
        "all foreseeable deployments.")
    assert len(long_requirement) > 400
    with pytest.raises(PydanticCustomError) as bounded:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id],
                questions={candidate.id: f"Does {candidate.primary_component} keep its contract substitutable?"},
                evidence_requirements={candidate.id: [
                    long_requirement,
                    "A drop-in implementation of LlmProvider ships without touching consumer code paths."]}), {})
    assert bounded.value.type == "planning_requirements_invalid"


def test_selection_validation_rejects_bundled_claims_or_components():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships),
        AbstractionRequest(documented_architecture=documentary(**_llm_provider_document())))
    execution = _executing(plan)
    candidate = plan.candidates[0]
    assert candidate.document_claim_ids, "expected a documented candidate in the provider fixture"

    with pytest.raises(PydanticCustomError) as compound_claims:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id],
                questions={candidate.id: f"Does {candidate.primary_component} keep its contract substitutable?"},
                evidence_requirements={candidate.id: [
                    f"LlmProvider must honor every stated obligation per {candidate.document_claim_ids[0]} and per {candidate.document_claim_ids[1]} at once",
                    "A drop-in implementation of LlmProvider ships without touching consumer code paths."]}), {})
    assert compound_claims.value.type == "planning_requirements_compound"

    with pytest.raises(PydanticCustomError) as compound_paths:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id],
                questions={candidate.id: f"Does {candidate.primary_component} keep its contract substitutable?"},
                evidence_requirements={candidate.id: [
                    "LlmProvider is implemented in src/llm/provider.py and consumed from src/llm/gemini.py and src/app/gateway.py with equal weight",
                    "A drop-in implementation of LlmProvider ships without touching consumer code paths."]}), {})
    assert compound_paths.value.type == "planning_requirements_compound"


def test_selection_validation_requires_an_obligation_anchor():
    files, symbols, relationships = _llm_provider_snapshot()
    plan = _plan(_snapshot(files, symbols, relationships))
    execution = _executing(plan)
    candidate = plan.candidates[0]

    with pytest.raises(PydanticCustomError) as unanchored:
        AbstractionExecution.prepare_structured_result(execution, "plan_investigation",
            AbstractionPlanSelection(candidate_ids=[candidate.id],
                questions={candidate.id: f"Does {candidate.primary_component} keep its contract substitutable?"},
                evidence_requirements={candidate.id: [
                    "Implementations must not leak vendor-specific configuration shapes to consumers.",
                    "Contract must support independent drop-in implementations for all consumers involved."]}), {})
    assert unanchored.value.type == "planning_requirements_invalid"
