"""Reusability V2 lifecycle; discovery never invokes registered participants."""

from server.blackboard.publication import publication_for
from server.runtimes.coordination.execution import CoordinatorAgent
from server.runtimes.invocation_reporting import phase_node

from .config import ReusabilityConfig
from .execution import ReusabilityExecution
from .registry import investigator_catalog
from .schemas import ReusabilityRequest


class ReusabilityCoordinator(CoordinatorAgent):
    agent_type = "reusability"
    config_type = ReusabilityConfig
    trace_name = "reusability-v2-coordinator"

    async def run(self, tools, request, *, capabilities=None):
        if self.blackboard is not None:
            self._blackboard_publication = publication_for(self)
        execution, state = self._execution(tools, request, capabilities)
        state = await self.tracing.wrap_stage(execution.graph.ainvoke(state, {"recursion_limit": 10}), name=self.trace_name)
        result = state["result"]
        publication = publication_for(self)
        if publication is not None and execution.timing.publication_allowed:
            publication.publish_assessment(result)
        return result

    def _execution(self, tools, request, capabilities):
        request = ReusabilityRequest.model_validate(request)
        if request.investigator_selection is not None:
            allowed = set(request.investigator_selection)
            full = investigator_catalog(None)
            capabilities = [capability for capability in full.values() if capability.id in allowed]
        catalog = investigator_catalog(capabilities)
        execution = ReusabilityExecution(self.model, self.config, tools, request)
        execution.owner = self
        if self.provider_pacer is not None and execution.provider_pacer.scope is None:
            execution.provider_pacer = self.provider_pacer
        state = execution.initial_state()
        state["investigator_catalog"] = list(catalog.values())
        return execution, state

    async def plan_assessment(self, tools, request, *, capabilities=None):
        """Explicit compatibility entry point: no delegation or finalization."""
        execution, state = self._execution(tools, request, capabilities)
        operation = phase_node("plan_assessment", execution.plan_assessment)
        update = await self.tracing.wrap_stage(operation(state, {}), name="plan_assessment")
        return {**state, **update}
