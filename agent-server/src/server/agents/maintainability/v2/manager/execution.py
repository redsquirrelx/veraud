"""Linear Manager graph: one cognitive planner, deterministic completion nodes."""

import inspect
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from server.contracts.audit import Consumption
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.invocation_reporting import phase_node

from .registry import coordinator_catalog
from .schemas import AuditPlan
from .state import MaintainabilityManagerState
from .validation import validate_plan


class MaintainabilityManagerExecution(InvestigationExecution):
    prompt_directory = Path(__file__).parent / "prompts"
    trace_name = "maintainability-v2-manager"

    def _build_graph(self):
        graph = StateGraph(MaintainabilityManagerState)
        names = ("plan_audit", "delegate_coordinators", "collect_assessments", "synthesize_assessments", "finalize_audit")
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
        return 0  # This slice has no later cognitive phases to reserve.

    def initial_state(self) -> MaintainabilityManagerState:
        repository = self.tools.accessible_snapshot.repository
        return {"request": self.request, "repository_id": repository.name, "commit": repository.commit,
            "snapshot_hash": repository.snapshot_hash, "coordinator_catalog": list(coordinator_catalog().values()), "plan": None,
            "limitations": [], "termination_reason": "", "consumption": Consumption(), "node_transitions": []}

    def _context(self, state):
        # Documentary input is carried in state for deterministic delegation only;
        # the manager's LLM must not read or reinterpret investigator context.
        return {"request": state["request"].model_dump(mode="json", exclude={"documented_architecture"}),
            "repository_id": state["repository_id"], "commit": state["commit"], "snapshot_hash": state["snapshot_hash"],
            "coordinator_catalog": [item.model_dump(mode="json") for item in state["coordinator_catalog"]]}

    async def plan_audit(self, state: MaintainabilityManagerState):
        self.logger.info("maintainability manager node=plan_audit")
        catalog = coordinator_catalog(state["coordinator_catalog"])
        # No conversation history: provenance is the original request in state.
        plan = await self.call("plan_audit", {**state, "messages": []}, AuditPlan)
        if plan is not None:
            try:
                plan = validate_plan(plan, state["request"], catalog,
                    {file.path for file in self.tools.accessible_snapshot.files})
            except ValueError as error:
                self.issues.append(f"plan_audit: {error}")
                self.logger.warning("plan_audit: %s", error)
                self.stop = "invalid_plan"
                plan = None
        limitations = list(dict.fromkeys([*state.get("limitations", []), *self.issues,
            *(plan.limitations if plan is not None else ["No valid audit plan was produced; no coordinators were executed."])]))
        return {"plan": plan, "limitations": limitations,
            "termination_reason": "" if plan is not None else self.stop or "invalid_plan",
            "consumption": Consumption(model_calls=self.calls, accounted_tokens=self.tokens, estimated_tokens=self.estimates)}

    async def delegate_coordinators(self, state: MaintainabilityManagerState):
        from .delegation import delegate_coordinators

        return await delegate_coordinators(self, state)

    def collect_assessments(self, state):
        from .collection import collect_assessments

        return collect_assessments(self, state)

    def synthesize_assessments(self, state):
        from .synthesis import synthesize_assessments

        return synthesize_assessments(self, state)

    def finalize_audit(self, state):
        from .synthesis import finalize_audit

        return finalize_audit(self, state)
