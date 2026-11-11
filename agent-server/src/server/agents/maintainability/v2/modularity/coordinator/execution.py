"""One cognitive planner followed by shared dispatch and deterministic collection."""

import inspect
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from server.contracts.audit import Consumption
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.invocation_reporting import phase_node

from .registry import investigator_catalog
from .schemas import AssessmentPlan
from .state import ModularityState
from .validation import validate_plan


class ModularityExecution(InvestigationExecution):
    prompt_directory = Path(__file__).parent / "prompts"
    trace_name = "modularity-v2-coordinator"

    def _build_graph(self):
        graph = StateGraph(ModularityState)
        names = ("plan_assessment", "delegate_investigations", "collect_findings", "finalize_assessment")
        for name in names:
            async def observed(state, name=name):
                update = getattr(self, name)(state)
                update = await update if inspect.isawaitable(update) else update
                return {**update, "node_transitions": [*state.get("node_transitions", []), name]}
            graph.add_node(name, phase_node(name, observed))
        for left, right in zip((START, *names), (*names, END), strict=True):
            graph.add_edge(left, right)
        return graph.compile()

    @property
    def closing_call_reserve(self):
        return 0

    def initial_state(self) -> ModularityState:
        repository = self.tools.accessible_snapshot.repository
        return {"request": self.request, "repository_id": repository.name, "commit": repository.commit,
            "snapshot_hash": repository.snapshot_hash, "investigator_catalog": list(investigator_catalog().values()),
            "plan": None, "limitations": [], "termination_reason": "", "consumption": Consumption(), "node_transitions": []}

    def _context(self, state):
        request = state["request"]
        # Preserve the full context in state, but never expose it to the planner.
        payload = request.model_dump(mode="json", exclude={"continuations", "documented_architecture"})
        payload["continuations"] = {} if not request.continuations else {key: "Native continuation available; not implementation evidence."
            for key in sorted(request.continuations)}
        return {"request": payload, "continuation_investigator_ids": sorted(request.continuations),
            "original_objective": request.original_objective or request.objective,
            "repository_id": state["repository_id"], "commit": state["commit"], "snapshot_hash": state["snapshot_hash"],
            "investigator_catalog": [item.model_dump(mode="json") for item in state["investigator_catalog"]]}

    async def plan_assessment(self, state: ModularityState):
        self.logger.info("modularity coordinator node=plan_assessment")
        catalog = investigator_catalog(state["investigator_catalog"])
        plan = await self.call("plan_assessment", {**state, "messages": []}, AssessmentPlan)
        if plan is not None:
            try:
                plan = validate_plan(plan, state["request"], catalog,
                    {file.path for file in self.tools.accessible_snapshot.files})
            except ValueError as error:
                self.issues.append(f"plan_assessment: {error}")
                self.logger.warning("plan_assessment: %s", error)
                self.stop = "invalid_plan"
                plan = None
        limitations = list(dict.fromkeys([*state.get("limitations", []), *self.issues,
            *(plan.limitations if plan is not None else ["No valid assessment plan was produced; no investigators were executed."])]))
        return {"plan": plan, "limitations": limitations,
            "termination_reason": "" if plan is not None else self.stop or "invalid_plan",
            "consumption": Consumption(model_calls=self.calls, accounted_tokens=self.tokens, estimated_tokens=self.estimates)}

    async def delegate_investigations(self, state):
        from .dispatch import delegate_investigations

        if state.get("plan") is None:
            return {"initial_plan": [], "execution_records": [], "investigation_results": []}
        return await delegate_investigations(self, state)

    def collect_findings(self, state):
        from .dispatch import collect_findings

        return collect_findings(self, state) if hasattr(self, "dispatch") else {"investigation_results": []}

    def finalize_assessment(self, state):
        from .finalization import finalize_assessment

        return finalize_assessment(self, state)
