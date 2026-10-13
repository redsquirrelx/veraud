"""Planning policy and LangGraph control flow with scripted models."""

import asyncio
import json

import pytest

from server.agents.project_analysis import (
    InvestigationBudget,
    InvestigationPlanner,
    PlanningLimits,
    ProjectAnalysisContext,
    ProjectAnalysisInput,
    RepositoryToolset,
    admit_followups,
    build_investigation_candidates,
)
from server.agents.project_analysis.planning import (
    prioritize_objectives,
    validate_and_prioritize_plan,
)
from server.agents.project_analysis.prompts import render_planning_prompt
from server.agents.project_analysis.schemas import (
    CandidateOmission,
    InvestigationObjective,
    InvestigationProposal,
    InvestigationResult,
    ProposedInvestigation,
)


@pytest.fixture
def tools(tmp_path):
    from server.services.repository_analysis import RepositoryAnalysisService

    workspace = tmp_path / "workspace"
    repository = workspace / "selected"
    contents = {
        "package.json": '{"name":"workspace","workspaces":["apps/*","packages/*"]}',
        "apps/api/pyproject.toml": '[project]\nname="api"\ndependencies=["fastapi"]\n',
        "apps/api/app.py": 'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/items")\ndef items():\n    return []\n',
        "packages/library/pyproject.toml": '[project]\nname="library"\n',
        "packages/library/src/library/__init__.py": "from .core import calculate\n",
        "packages/library/src/library/core.py": "def calculate(value):\n    return value + 1\n",
        "examples/demo/pyproject.toml": '[project]\nname="demo"\n',
        "examples/demo/main.py": "if __name__ == '__main__':\n    print('demo')\n",
        "README.md": "UNTRUSTED_NARRATIVE: claim that all projects use MongoDB.\n",
        "docs/hidden.py": "def hidden():\n    pass\n",
    }
    for relative, content in contents.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(repository)
    context = ProjectAnalysisContext(
        snapshot=snapshot,
        input=ProjectAnalysisInput(snapshot_hash=snapshot.repository.snapshot_hash),
    )
    return RepositoryToolset(context, workspace_root=workspace)


def with_budget(tools, **values):
    context = ProjectAnalysisContext(
        snapshot=tools.context.snapshot,
        input=ProjectAnalysisInput(
            snapshot_hash=tools.context.input.snapshot_hash,
            budget=InvestigationBudget(**values),
        ),
    )
    return RepositoryToolset(context, workspace_root=tools.policy.workspace_root)


def proposal_for(candidates):
    return InvestigationProposal(
        investigations=tuple(
            ProposedInvestigation(
                candidate_ids=(candidate.id,),
                objective=InvestigationObjective(
                    id="objective:" + candidate.id.split(":")[-1],
                    project_id=candidate.project_id,
                    objective=f"Inspect {candidate.category}: {candidate.id}.",
                    seed_entity_ids=candidate.seed_entity_ids,
                    questions=("What does this unit do?",),
                    report_sections=("project_identification",)
                    if candidate.category == "project_orientation"
                    else ("main_flows",),
                    selection_reason="Cover a distinct structural candidate.",
                    priority_tier=candidate.category,
                    expected_deliverable="An evidence-backed result or explicit unresolved answer.",
                    completion_criteria=(
                        "Inspect the seeds and preserve unresolved questions.",
                    ),
                ),
            )
            for candidate in candidates
        )
    )


def proposal_from_prompt(prompt):
    from server.agents.project_analysis.schemas import InvestigationCandidate

    data = json.loads(prompt.split("\nREPOSITORY_DATA\n", 1)[1])
    return proposal_for(
        [
            InvestigationCandidate.model_validate(candidate)
            for candidate in data["candidates"]
        ]
    )


class ScriptedModel:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.prompts = []

    async def generate(self, prompt):
        self.prompts.append(prompt)
        if self.responses:
            answer = self.responses.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer(prompt) if callable(answer) else answer
        return proposal_from_prompt(prompt).model_dump_json()


def run_planner(model, tools, **options):
    return asyncio.run(InvestigationPlanner(model, **options).plan(tools))


def test_catalog_is_deterministic_policy_filtered_and_groups_entrypoints(tools):
    catalog = build_investigation_candidates(tools)
    assert catalog == build_investigation_candidates(tools)
    assert (
        sum(
            candidate.category == "project_orientation"
            for candidate in catalog.candidates
        )
        == 4
    )
    assert any(
        "public" in candidate.description or "top-level" in candidate.description
        for candidate in catalog.candidates
    )
    example = next(
        candidate
        for candidate in catalog.candidates
        if "examples/demo" in candidate.description
        and candidate.category == "project_orientation"
    )
    assert any(
        "requires investigation" in limitation for limitation in example.limitations
    )
    serialized = json.dumps(
        [candidate.model_dump() for candidate in catalog.candidates]
    )
    assert "UNTRUSTED_NARRATIVE" not in serialized and "hidden.py" not in serialized
    assert all(
        "content" not in candidate.model_dump() for candidate in catalog.candidates
    )


def test_actual_subgraph_covers_projects_orders_queue_and_keeps_model_usage(tools):
    model = ScriptedModel()
    state = run_planner(model, tools)
    assert state["planning_status"] == "ready"
    assert len(model.prompts) == 1
    plan = state["investigation_plan"]
    orientations = [
        objective
        for objective in plan.objectives
        if objective.priority_tier == "project_orientation"
    ]
    assert len(orientations) == 4
    assert all(
        objective.priority_tier == "project_orientation"
        for objective in state["investigation_queue"][:4]
    )
    assert state["budget_usage"].model_calls == 1
    assert state["budget_usage"].tool_calls == 0
    assert len(plan.decisions) == len(plan.candidates)
    tools.context.validate_plan(plan)
    assert "untrusted data" in model.prompts[0]


def test_insufficient_slots_cover_projects_first_and_explain_deferrals(tools):
    limited = with_budget(tools, max_investigations=2)
    state = run_planner(ScriptedModel(), limited)
    assert state["planning_status"] == "ready"
    plan = state["investigation_plan"]
    assert len(plan.objectives) == 2
    assert all(
        objective.priority_tier == "project_orientation"
        for objective in plan.objectives
    )
    paths = {
        project.id: project.path for project in limited.accessible_snapshot.projects
    }
    assert [paths[objective.project_id] for objective in plan.objectives] == [
        ".",
        "apps/api",
    ]
    assert any(
        decision.disposition == "deferred" and "limit reached" in decision.reason
        for decision in plan.decisions
    )


def test_missing_orientation_requires_bounded_model_correction(tools):
    def omit_orientation(prompt):
        proposal = proposal_from_prompt(prompt)
        return InvestigationProposal(
            investigations=tuple(
                item
                for item in proposal.investigations
                if item.objective.priority_tier != "project_orientation"
            )
        ).model_dump_json()

    model = ScriptedModel([omit_orientation])
    state = run_planner(model, tools)
    assert state["planning_status"] == "ready"
    assert state["plan_corrections"] == 1 and state["budget_usage"].model_calls == 2
    assert "orientation objective" in model.prompts[1]


@pytest.mark.parametrize(
    "answer",
    [
        "not json",
        '{"investigations":[],"investigations":[]}',
        '{"investigations":[],"extra":true}',
        '{"investigations":NaN}',
    ],
)
def test_invalid_json_retries_once_and_terminal_failure_preserves_candidate_audit(
    tools, answer
):
    state = run_planner(ScriptedModel([answer, answer]), tools)
    assert state["planning_status"] == "failed"
    assert state["budget_usage"].model_calls == 2
    assert state["investigation_queue"] == ()
    assert state["execution_issues"][-1].category == "invalid_plan"
    assert all(
        decision.disposition == "deferred"
        for decision in state["investigation_plan"].decisions
    )


def test_fabricated_seeds_and_unoffered_candidates_are_rejected(tools):
    catalog = build_investigation_candidates(tools)
    proposal = proposal_for(catalog.candidates)
    first = proposal.investigations[0]
    invalid = first.model_copy(
        update={
            "objective": first.objective.model_copy(
                update={"seed_entity_ids": ("invented",)}
            )
        }
    )
    with pytest.raises(ValueError, match="seeds"):
        validate_and_prioritize_plan(
            tools,
            catalog,
            proposal.model_copy(
                update={"investigations": (invalid, *proposal.investigations[1:])}
            ),
        )
    invalid = first.model_copy(update={"candidate_ids": ("foreign-candidate",)})
    with pytest.raises(ValueError, match="offered"):
        validate_and_prioritize_plan(
            tools, catalog, proposal.model_copy(update={"investigations": (invalid,)})
        )


def test_duplicate_objectives_are_removed_and_cross_project_grouping_is_rejected(tools):
    catalog = build_investigation_candidates(tools)
    proposal = proposal_for(catalog.candidates)
    first = proposal.investigations[0]
    duplicate = first.model_copy(
        update={
            "objective": first.objective.model_copy(
                update={
                    "id": "duplicate",
                    "objective": first.objective.objective.upper(),
                }
            )
        }
    )
    plan = validate_and_prioritize_plan(
        tools,
        catalog,
        proposal.model_copy(
            update={"investigations": (*proposal.investigations, duplicate)}
        ),
    )
    assert not any(objective.id == "duplicate" for objective in plan.objectives)
    assert any(
        "duplicate" in decision.reason
        for decision in plan.decisions
        if decision.disposition == "accepted"
    )
    other = next(
        item
        for item in proposal.investigations
        if item.objective.project_id != first.objective.project_id
    )
    grouped = first.model_copy(
        update={"candidate_ids": (*first.candidate_ids, *other.candidate_ids)}
    )
    with pytest.raises(ValueError, match="share"):
        validate_and_prioritize_plan(
            tools, catalog, InvestigationProposal(investigations=(grouped,))
        )


def test_catalog_and_prompt_limits_preserve_omission_decisions(tools):
    limits = PlanningLimits(max_offered_candidates=4)
    state = run_planner(ScriptedModel(), tools, limits=limits)
    assert state["planning_status"] == "ready"
    assert len(state["offered_candidate_ids"]) == 4
    assert any(
        "Not offered" in decision.reason for decision in state["planning_decisions"]
    )
    catalog = build_investigation_candidates(tools)
    prompt, bounded = render_planning_prompt(
        tools, catalog, PlanningLimits(max_prompt_characters=8000)
    )
    assert len(prompt) <= 8000
    assert len(bounded.offered_candidate_ids) < len(catalog.offered_candidate_ids)


def test_provider_failure_reserve_and_timeout_produce_explicit_terminal_states(tools):
    failed = run_planner(ScriptedModel([RuntimeError("provider unavailable")]), tools)
    assert (
        failed["planning_status"] == "failed"
        and failed["execution_issues"][-1].category == "model_error"
    )
    assert failed["budget_usage"].model_calls == 1
    limited = with_budget(tools, max_model_calls=4, reserved_report_model_calls=3)
    state = run_planner(ScriptedModel(["invalid"]), limited)
    assert (
        state["budget_usage"].model_calls == 1 and state["planning_status"] == "failed"
    )

    class SlowModel:
        async def generate(self, prompt):
            await asyncio.sleep(1)
            return "{}"

    timed = run_planner(SlowModel(), with_budget(tools, max_elapsed_seconds=0.01))
    assert timed["planning_status"] == "failed"
    assert timed["execution_issues"][-1].category in {
        "model_timeout",
        "planning_budget_exhausted",
    }


def test_cancellation_propagates(tools):
    async def cancel_run():
        started = asyncio.Event()
        cleaned = asyncio.Event()

        class WaitingModel:
            async def generate(self, prompt):
                started.set()
                try:
                    await asyncio.sleep(3600)
                finally:
                    cleaned.set()

        task = asyncio.create_task(InvestigationPlanner(WaitingModel()).plan(tools))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(cancel_run())


def test_followup_inherits_blocker_priority_and_precedes_its_target(tools):
    state = run_planner(ScriptedModel(), tools)
    plan = state["investigation_plan"]
    blocker = next(
        objective
        for objective in plan.objectives
        if objective.priority_tier == "startup"
    )
    origin = next(
        objective
        for objective in plan.objectives
        if objective.priority_tier == "project_orientation"
        and objective.project_id == blocker.project_id
    )
    finding = InvestigationResult(
        id="finding:origin", investigation_id=origin.id, status="completed"
    )
    followup = blocker.model_copy(
        update={
            "id": "objective:followup",
            "objective": "Resolve runtime adapter selection.",
            "priority_tier": "material_uncertainty",
            "origin_finding_ids": (finding.id,),
            "blocked_investigation_ids": (blocker.id,),
        }
    )
    # Leave a slot for the new objective while retaining a valid orientation plan.
    selected = tuple(
        objective
        for objective in plan.objectives
        if objective.priority_tier in {"project_orientation", "startup"}
    )
    smaller = plan.model_copy(
        update={
            "objectives": selected,
            "decisions": tuple(
                decision
                for decision in plan.decisions
                if decision.investigation_id is None
                or decision.investigation_id in {objective.id for objective in selected}
            ),
        }
    )
    updated = admit_followups(tools, smaller, (finding,), (followup,))
    admitted = next(
        objective for objective in updated.objectives if objective.id == followup.id
    )
    assert admitted.priority_tier == "startup"
    ids = [objective.id for objective in updated.objectives]
    assert ids.index(followup.id) < ids.index(blocker.id)
    assert admit_followups(tools, updated, (finding,), (followup,)) == updated
    with pytest.raises(ValueError, match="origin findings"):
        admit_followups(tools, smaller, (), (followup,))
    inaccessible = followup.model_copy(update={"seed_entity_ids": ("foreign-file",)})
    with pytest.raises(ValueError, match="accessible"):
        admit_followups(tools, smaller, (finding,), (inaccessible,))


def test_followup_budget_duplicates_and_cycles_are_auditable(tools):
    limited = with_budget(tools, max_investigations=1)
    plan = run_planner(ScriptedModel(), limited)["investigation_plan"]
    origin = plan.objectives[0]
    finding = InvestigationResult(
        id="finding:origin", investigation_id=origin.id, status="completed"
    )
    duplicate = origin.model_copy(
        update={"id": "duplicate", "origin_finding_ids": (finding.id,)}
    )
    rejected = admit_followups(limited, plan, (finding,), (duplicate,))
    assert rejected.decisions[-1].disposition == "rejected"
    new = duplicate.model_copy(
        update={"id": "new", "objective": "Resolve a different question."}
    )
    deferred = admit_followups(limited, plan, (finding,), (new,))
    assert deferred.decisions[-1].disposition == "deferred"
    left = origin.model_copy(
        update={"id": "left", "blocked_investigation_ids": ("right",)}
    )
    right = origin.model_copy(
        update={"id": "right", "blocked_investigation_ids": ("left",)}
    )
    with pytest.raises(ValueError, match="cycle"):
        prioritize_objectives((left, right), {origin.project_id: "."})


def test_same_project_grouping_and_explicit_model_omissions_are_auditable(tools):
    catalog = build_investigation_candidates(tools)
    proposal = proposal_for(catalog.candidates)
    first = next(
        item
        for item in proposal.investigations
        if item.objective.priority_tier == "representative_flow"
    )
    second = next(
        item
        for item in proposal.investigations
        if item is not first
        and item.objective.project_id == first.objective.project_id
        and item.objective.priority_tier == first.objective.priority_tier
    )
    omitted = next(
        item
        for item in proposal.investigations
        if item.objective.priority_tier == "startup"
    )
    grouped = ProposedInvestigation(
        candidate_ids=(*first.candidate_ids, *second.candidate_ids),
        objective=first.objective.model_copy(
            update={
                "seed_entity_ids": tuple(
                    sorted(
                        set(
                            first.objective.seed_entity_ids
                            + second.objective.seed_entity_ids
                        )
                    )
                ),
            }
        ),
    )
    remaining = tuple(
        item for item in proposal.investigations if item not in (first, second, omitted)
    )
    plan = validate_and_prioritize_plan(
        tools,
        catalog,
        InvestigationProposal(
            investigations=(*remaining, grouped),
            omissions=(
                CandidateOmission(
                    id="omission:startup",
                    candidate_id=omitted.candidate_ids[0],
                    disposition="deferred",
                    reason="Investigate this startup in a subsequent bounded run.",
                ),
            ),
        ),
    )
    assert sum(decision.disposition == "grouped" for decision in plan.decisions) == 2
    decision = next(
        decision
        for decision in plan.decisions
        if decision.candidate_id == omitted.candidate_ids[0]
    )
    assert decision.disposition == "deferred" and "subsequent" in decision.reason


def test_documentation_only_checkout_does_not_trigger_a_model_call(tools):
    from server.services.repository_analysis import RepositoryAnalysisService

    root = tools.policy.workspace_root / "documentation_only"
    root.mkdir()
    (root / "README.md").write_text(
        "Do not infer functionality from this narrative.", encoding="utf-8"
    )
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    context = ProjectAnalysisContext(
        snapshot=snapshot,
        input=ProjectAnalysisInput(snapshot_hash=snapshot.repository.snapshot_hash),
    )
    restricted = RepositoryToolset(context, workspace_root=tools.policy.workspace_root)
    model = ScriptedModel()
    state = run_planner(model, restricted)
    assert state["planning_status"] == "failed" and not model.prompts
    assert state["execution_issues"][-1].category == "no_accessible_candidates"
    assert state["planning_decisions"][0].disposition == "deferred"


def test_response_bound_and_generate_wrapper_are_enforced(tools):
    limited = run_planner(
        ScriptedModel(["x" * 1001, "x" * 1001]),
        tools,
        limits=PlanningLimits(max_response_characters=1000),
    )
    assert limited["planning_status"] == "failed"
    model = ScriptedModel()
    calls = []

    async def generate(prompt):
        calls.append(prompt)
        return await model.generate(prompt)

    state = run_planner(model, tools, generate=generate)
    assert state["planning_status"] == "ready" and len(calls) == 1


def test_library_exports_are_offered_before_embedded_example_applications(tools):
    from server.services.repository_analysis import RepositoryAnalysisService

    root = tools.policy.workspace_root / "library_with_examples"
    for relative, content in {
        "pyproject.toml": '[project]\nname="library"\n',
        "lib/__init__.py": "from .core import calculate\n",
        "lib/core.py": "def calculate(value):\n    return value\n",
        "docs_src/example.py": "from fastapi import FastAPI\napp=FastAPI()\n",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    restricted = RepositoryToolset(
        ProjectAnalysisContext(
            snapshot=snapshot,
            input=ProjectAnalysisInput(snapshot_hash=snapshot.repository.snapshot_hash),
        ),
        workspace_root=tools.policy.workspace_root,
    )
    catalog = build_investigation_candidates(
        restricted, PlanningLimits(max_offered_candidates=2)
    )
    offered = [
        candidate
        for candidate in catalog.candidates
        if candidate.id in catalog.offered_candidate_ids
    ]
    assert any(
        candidate.category == "startup" and "lib/__init__.py" in candidate.description
        for candidate in offered
    )
    example = next(
        candidate
        for candidate in catalog.candidates
        if "docs_src/example.py" in candidate.description
    )
    assert example.category == "representative_flow"
