"""Offline coordinator planning and discovery through the actual V2 Manager."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_architecture_boundary_planning import tools_for
from test_maintainability_v2_plan_audit import Model

from server.agents.maintainability.v2.manager import (
    MaintainabilityManager,
    MaintainabilityRequest,
)
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.manager.execution import (
    MaintainabilityManagerExecution,
)
from server.agents.maintainability.v2.manager.registry import (
    coordinator_catalog,
    registered_coordinators,
)
from server.agents.maintainability.v2.modularity.coordinator import (
    AssessmentPlan,
    AssessmentRequest,
    AssessmentResult,
    ModularityConfig,
    ModularityCoordinator,
)
from server.agents.maintainability.v2.modularity.coordinator.execution import (
    ModularityExecution,
)
from server.agents.maintainability.v2.modularity.coordinator.registry import (
    investigator_catalog,
    registered_investigators,
)


class Tracing:
    async def wrap_stage(self, operation, **metadata):
        assert metadata["name"] in {"plan_audit", "plan_assessment"}
        return await operation


@pytest.fixture
def tools(tmp_path):
    return tools_for(tmp_path, {"Checkout/api.py": "class Checkout: pass\n", "Checkout/store.py": "class Store: pass\n",
        "Inventory/api.py": "class Inventory: pass\n"})


def assignment(identifier="architecture_boundary", **changes):
    return {"investigator_id": identifier, "objective": "Examine architectural boundaries in Checkout.",
        "targets": [], "constraints": [], "rationale": "The delegated request concerns Checkout architectural boundaries."} | changes


def plan(*assignments, **changes):
    return {"objective": "Assess the requested architecture concerns.", "assignments": list(assignments),
        "uncovered_requirements": [], "limitations": []} | changes


def execute(tools, response, request=None, capabilities=None):
    model = Model(response)
    request = request or AssessmentRequest(objective="Investigate architecture in Checkout.")
    execution = ModularityExecution(model, ModularityConfig(provider_request_interval_seconds=0), tools, request)
    state = execution.initial_state()
    if capabilities is not None:
        state["investigator_catalog"] = capabilities
    before = dict(state)
    update = asyncio.run(execution.plan_assessment(state))
    assert state == before and execution.graph is not None
    assert tools.budget_usage.tool_calls == 0
    assert update["consumption"].model_calls == len(model.contexts) == 1
    assert update["consumption"].accounted_tokens == 120
    return update, model.contexts[0]


def test_real_catalog_contains_only_documentary_boundary_v2(tools):
    update, context = execute(tools, plan(assignment()))
    assert [item.investigator_id for item in update["plan"].assignments] == ["architecture_boundary"]
    assert [item["id"] for item in context["investigator_catalog"]] == ["architecture_boundary"]
    assert context["snapshot_hash"] == tools.accessible_snapshot.repository.snapshot_hash
    assert context["original_objective"] == "Investigate architecture in Checkout."


def test_distinct_objectives_use_only_the_available_specialty(tools):
    update, _ = execute(tools, plan(assignment(), assignment(
        objective="Investigate another documented Checkout interaction.", rationale="A distinct boundary interaction is requested.")))
    assert len(update["plan"].assignments) == len({item.objective for item in update["plan"].assignments}) == 2


def test_general_architecture_request_does_not_require_all_investigators(tools):
    update, context = execute(tools, plan(assignment(objective="Assess documented boundaries.")),
        AssessmentRequest(objective="Evaluate repository architecture."))
    assert len(update["plan"].assignments) == 1
    assert context["request"]["objective"] == "Evaluate repository architecture."


def test_scoped_checkout_preserves_original_and_delegated_objectives_and_restrictions(tools):
    request = AssessmentRequest(objective="Examine architecture in Checkout.", original_objective="Audit maintainability in Checkout.",
        targets=["Checkout/"], constraints=["Do not inspect Inventory.", "No changes."], repository_context="Application context.")
    update, context = execute(tools, plan(assignment()), request)
    row = update["plan"].assignments[0]
    assert row.targets == ["Checkout"]
    assert set(request.constraints) <= set(row.constraints)
    assert set(investigator_catalog()[row.investigator_id].constraints) <= set(row.constraints)
    assert context["request"] == request.model_dump(exclude={"documented_architecture"})
    assert context["original_objective"] == request.original_objective


def test_semantic_checkout_without_a_path_is_not_invented_or_discarded(tools):
    update, _ = execute(tools, plan(assignment(), limitations=["Checkout has no supplied path; semantic scope is retained."]))
    assert update["plan"].assignments[0].targets == []
    assert "Checkout" in update["plan"].assignments[0].objective
    assert "semantic scope" in update["limitations"][0]


@pytest.mark.parametrize("capabilities", [[], [investigator_catalog()["architecture_boundary"]]])
def test_empty_or_incompatible_partial_catalog_retains_uncovered_requirements(tools, capabilities):
    update, context = execute(tools, plan(uncovered_requirements=["Dependency-impact specialist unavailable."]), capabilities=capabilities)
    assert update["plan"].assignments == []
    assert update["plan"].uncovered_requirements == ["Dependency-impact specialist unavailable."]
    assert len(context["investigator_catalog"]) == len(capabilities)


def test_partial_catalog_can_select_only_its_available_investigator(tools):
    update, _ = execute(tools, plan(assignment()), capabilities=[investigator_catalog()["architecture_boundary"]])
    assert update["plan"].assignments[0].investigator_id == "architecture_boundary"


@pytest.mark.parametrize("identifier", ["invented", "dependency_impact", "responsibility"])
def test_unknown_or_unavailable_id_fails_without_fallback_plan(tools, identifier):
    update, _ = execute(tools, plan(assignment(identifier)), capabilities=[investigator_catalog()["architecture_boundary"]])
    assert update["plan"] is None and update["termination_reason"] == "invalid_plan"
    assert "plan_assessment: unknown_investigator" in update["limitations"]


def test_exact_duplicates_removed_without_merging_distinct_assignments(tools):
    update, _ = execute(tools, plan(assignment(), assignment(), assignment(objective="Examine another requested interaction.")))
    assert len(update["plan"].assignments) == 2


@pytest.mark.parametrize("targets", [["Inventory"], ["CheckoutOther"], ["../Checkout"], ["/Checkout"], ["Checkout/missing.py"]])
def test_scope_expansion_and_invalid_paths_are_rejected(tools, targets):
    update, _ = execute(tools, plan(assignment(targets=targets)), AssessmentRequest(objective="Checkout only.", targets=["Checkout"]))
    assert update["plan"] is None and update["termination_reason"] == "invalid_plan"
    assert any("scope" in text for text in update["limitations"])


def test_valid_narrow_scope_and_assignment_constraints_survive(tools):
    update, _ = execute(tools, plan(assignment(targets=["Checkout\\api.py"], constraints=["Keep uncertainty explicit."])),
        AssessmentRequest(objective="Checkout only.", targets=["Checkout"], constraints=["Read only."]))
    row = update["plan"].assignments[0]
    assert row.targets == ["Checkout/api.py"]
    assert {"Keep uncertainty explicit.", "Read only."} <= set(row.constraints)


@pytest.mark.parametrize("response", ["not JSON", {"assignments": []}, plan(assignment(objective="")),
    plan(assignment(tools=["get_source_excerpt"])), plan()])
def test_invalid_response_and_unexplained_empty_plan_are_explicit(tools, response):
    update, _ = execute(tools, response)
    assert update["plan"] is None and update["termination_reason"]
    assert update["limitations"]


def test_order_and_serialization_are_deterministic(tools):
    model = Model(plan(assignment(), assignment(objective="Another boundary interaction."), limitations=["Partial coverage only."]))
    execution = ModularityExecution(model, ModularityConfig(provider_request_interval_seconds=0), tools,
        AssessmentRequest(objective="Audit architecture."))
    state = execution.initial_state() | {"limitations": ["Prior limitation."]}
    first = asyncio.run(execution.plan_assessment(state))
    model.response["assignments"].reverse()
    second = asyncio.run(execution.plan_assessment(state))
    assert first["plan"] == second["plan"]
    assert first["limitations"] == ["Prior limitation.", "Partial coverage only."]
    assert AssessmentPlan.model_validate_json(first["plan"].model_dump_json()) == first["plan"]


def test_catalogs_bind_real_contracts_and_discovery_does_not_construct_agents(monkeypatch):
    specs = registered_investigators()
    assert set(specs) == {"architecture_boundary"}
    assert specs["architecture_boundary"].agent_class.__module__.endswith("architecture_boundary_doc_driven.agent")
    for key, spec in specs.items():
        assert spec.capability.id == key and spec.capability.problem_types and spec.capability.constraints
        assert "objective" not in spec.request_class.model_fields
        assert "constraints" in spec.request_class.model_fields and "findings" in spec.result_class.model_fields

    def forbidden(*args, **kwargs):
        raise AssertionError("Discovery must not instantiate participants.")

    for spec in specs.values():
        monkeypatch.setattr(spec.agent_class, "__init__", forbidden)
    monkeypatch.setattr(ModularityCoordinator, "__init__", forbidden)
    coordinators = registered_coordinators()
    assert coordinators["modularity"].agent_class is ModularityCoordinator
    assert coordinators["modularity"].request_class is AssessmentRequest
    assert set(coordinators["modularity"].capability.problem_types) == {
        problem for spec in specs.values() for problem in spec.capability.problem_types}
    assert coordinator_catalog([]) == {} and investigator_catalog([]) == {}


@pytest.mark.parametrize("identifier", ["responsibility", "dependency_impact"])
def test_catalog_override_cannot_reintroduce_legacy_investigators(tools, identifier):
    unavailable = investigator_catalog()["architecture_boundary"].model_copy(update={"id": identifier})
    model = Model(plan(assignment(identifier)))
    coordinator = ModularityCoordinator(model, ModularityConfig(provider_request_interval_seconds=0), tracing_backend=Tracing())
    with pytest.raises(ValueError, match="not registered"):
        asyncio.run(coordinator.plan_assessment(tools, AssessmentRequest(objective="Checkout"), capabilities=[unavailable]))
    assert not model.contexts


def test_manager_advertises_only_the_actual_documentary_boundary_capabilities():
    actual = registered_investigators()["architecture_boundary"].capability
    advertised = registered_coordinators()["modularity"].capability
    assert advertised.problem_types == sorted(actual.problem_types)
    assert "mixed responsibilities" not in advertised.problem_types
    assert "harmful coupling" not in advertised.problem_types


def test_manager_default_node_state_discovers_modularity(tools):
    execution = MaintainabilityManagerExecution(Model({}), MaintainabilityConfig(provider_request_interval_seconds=0), tools,
        MaintainabilityRequest(objective="Architecture in Checkout."))
    assert [item.id for item in execution.initial_state()["coordinator_catalog"]] == ["modularity", "reusability"]


def test_manager_to_modularity_planning_integration_without_delegation(tools, monkeypatch):
    original = "Investiga problemas arquitectónicos en Checkout"
    for spec in registered_investigators().values():
        async def forbidden(*args, **kwargs):
            raise AssertionError("No investigator may execute during planning.")
        monkeypatch.setattr(spec.agent_class, "run", forbidden)
    manager_model = Model({"objective": original, "assignments": [{"coordinator_id": "modularity",
        "objective": "Evalúa los límites arquitectónicos de Checkout.", "scope": [], "constraints": [],
        "rationale": "La solicitud pide evaluar la arquitectura de Checkout."}],
        "uncovered_requirements": [], "limitations": ["Checkout se mantiene como alcance semántico."]})
    manager = MaintainabilityManager(manager_model, MaintainabilityConfig(provider_request_interval_seconds=0), tracing_backend=Tracing())
    manager_state = asyncio.run(manager.plan_audit(tools, MaintainabilityRequest(objective=original, constraints=["Solo lectura."])))
    delegated = manager_state["plan"].assignments[0]
    spec = registered_coordinators()[delegated.coordinator_id]
    request = spec.request_class(objective=delegated.objective, original_objective=manager_state["request"].objective,
        targets=delegated.scope, constraints=delegated.constraints)
    coordinator_model = Model(plan(assignment(objective="Examina los límites de Checkout.")))
    coordinator = spec.agent_class(coordinator_model, ModularityConfig(provider_request_interval_seconds=0), tracing_backend=Tracing())
    # Explicit invocation of the planner in this test is not Manager delegation.
    state = asyncio.run(coordinator.plan_assessment(tools, request))
    assert state["plan"].assignments[0].investigator_id == "architecture_boundary"
    assert state["plan"].assignments[0].targets == []
    assert state["request"].original_objective == original
    assert "Solo lectura." in state["plan"].assignments[0].constraints
    assert manager_model.contexts[0]["coordinator_catalog"][0]["id"] == "modularity"
    assert len(manager_model.contexts) == len(coordinator_model.contexts) == 1
    assert tools.budget_usage.tool_calls == 0


def test_duplicate_catalog_ids_and_direct_tools_rejected():
    capability = investigator_catalog()["architecture_boundary"]
    with pytest.raises(ValueError, match="Duplicate investigator"):
        investigator_catalog([capability, capability])
    with pytest.raises(ValidationError):
        ModularityConfig(tools=["list_files"])


def test_provider_failure_retains_estimated_consumption_and_safe_diagnostic(tools):
    model = Model(RuntimeError("secret provider payload"))
    execution = ModularityExecution(model, ModularityConfig(provider_request_interval_seconds=0), tools,
        AssessmentRequest(objective="Assess architecture."))
    update = asyncio.run(execution.plan_assessment(execution.initial_state()))
    assert update["plan"] is None and update["termination_reason"]
    assert update["consumption"].model_calls == 1 and update["consumption"].accounted_tokens > 0
    assert "secret provider payload" not in str(update["limitations"])


def test_native_structured_response_still_rejects_unknown_investigators(tools):
    class NativeModel(Model):
        def with_structured_output(self, schema, **kwargs):
            assert schema is AssessmentPlan and kwargs["include_raw"] is True
            return self

        async def ainvoke(self, messages, **kwargs):
            raw = await super().ainvoke(messages, **kwargs)
            return {"raw": raw, "parsed": self.response, "parsing_error": None}

    model = NativeModel(plan(assignment("invented")))
    execution = ModularityExecution(model, ModularityConfig(provider_request_interval_seconds=0), tools,
        AssessmentRequest(objective="Assess architecture."))
    update = asyncio.run(execution.plan_assessment(execution.initial_state()))
    assert update["plan"] is None and update["termination_reason"] == "invalid_plan"
    assert update["consumption"].accounted_tokens == 120


@pytest.fixture
def runner(monkeypatch):
    path = Path(__file__).parents[1] / "src/test-agents/run_modularity_coordinator_v2.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("modularity_v2_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def test_independent_runner_stops_after_plan_assessment(tmp_path, runner, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "api.py").write_text("class API: pass\n", encoding="utf-8")
    output = tmp_path / "plan.json"
    output.write_text("old result", encoding="utf-8")
    args = runner.parser().parse_args([str(root), "--prompt", "Architecture in Checkout", "--original-prompt", "Maintainability in Checkout",
        "--target", "api.py", "--constraint", "Read only", "--output-file", str(output), "--plan-only"])
    request = AssessmentRequest(objective=args.prompt, original_objective=args.original_prompt,
        targets=args.target, constraints=args.constraint)
    model = Model(plan(assignment()))
    state = asyncio.run(runner.run_plan(args, request, list(investigator_catalog().values()),
        ModularityConfig(provider_request_interval_seconds=0), model, SimpleNamespace(max_tokens=1800), tracing_backend=Tracing()))
    data = json.loads(output.read_text(encoding="utf-8"))
    assert AssessmentPlan.model_validate(data["plan"]) == state["plan"]
    assert data["request"]["original_objective"] == args.original_prompt
    assert data["plan"]["assignments"][0]["targets"] == ["api.py"]
    assert data["consumption"]["model_calls"] == len(model.contexts) == 1
    assert data["consumption"]["tool_calls"] == 0
    assert "plan_assessment · sin delegaciones ni investigaciones" in capsys.readouterr().out


@pytest.mark.parametrize("options,expected", [(["--investigator", "architecture_boundary"], ["architecture_boundary"]),
    (["--no-investigators"], [])])
def test_runner_respects_registered_subset_or_empty_catalog(runner, monkeypatch, options, expected):
    args = runner.parser().parse_args(["repo", "--prompt", "Assess architecture", *options])
    model, closed = object(), []
    monkeypatch.setattr(runner, "load_test_model", lambda key: (model, SimpleNamespace(max_tokens=1800)))

    async def inspect(args, request, capabilities, config, model, settings, **kwargs):
        assert [item.id for item in capabilities] == expected
        return "planning-only"

    async def close(wrapper):
        closed.append(wrapper.llm)

    monkeypatch.setattr(runner, "run_plan", inspect)
    monkeypatch.setattr(runner, "close_model_clients", close)
    assert asyncio.run(runner.run(args)) == "planning-only"
    assert closed == [model]


@pytest.mark.parametrize("identifier", ["invented", "responsibility", "dependency_impact"])
def test_runner_rejects_unregistered_selection_before_model_creation(runner, monkeypatch, identifier):
    def forbidden(*args):
        raise AssertionError("Unknown selection must fail before loading a provider.")

    monkeypatch.setattr(runner, "load_test_model", forbidden)
    args = runner.parser().parse_args(["repo", "--prompt", "Audit", "--investigator", identifier])
    with pytest.raises(ValueError, match="Unknown investigator"):
        asyncio.run(runner.run(args))


def test_runner_default_reaches_final_assessment_without_inventing_investigations(tmp_path, runner, capsys):
    class FullTracing:
        async def wrap_stage(self, operation, **metadata):
            assert metadata["name"] == "modularity-v2-coordinator"
            return await operation

    root = tmp_path / "repo"
    root.mkdir()
    (root / "api.py").write_text("class API: pass\n", encoding="utf-8")
    destination = tmp_path / "assessment.json"
    args = runner.parser().parse_args([str(root), "--prompt", "Unsupported objective", "--output-file", str(destination)])
    model = Model(plan(uncovered_requirements=["No applicable investigator."]))
    result = asyncio.run(runner.run_plan(args, AssessmentRequest(objective=args.prompt), [],
        ModularityConfig(provider_request_interval_seconds=0), model, SimpleNamespace(max_tokens=1800), tracing_backend=FullTracing()))
    assert result.status == "not_applicable" and not result.invocations
    assert result.node_transitions[-1] == "finalize_assessment"
    assert AssessmentResult.model_validate_json(destination.read_text(encoding="utf-8")).model_dump(mode="json") == result.model_dump(mode="json")
    assert len(model.contexts) == result.consumption.model_calls == 1
    assert "Modularidad: not_applicable" in capsys.readouterr().out
