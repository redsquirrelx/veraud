"""Public reusability-coordinator lifecycle; graph and synthesis rules live alongside it."""

from config.agents import CoordinatorConfig as ReusabilityConfig

from .....runtimes.coordination.execution import CoordinatorAgent
from .....runtimes.repository.access import repository_relative_path
from .execution import ReusabilityExecution, route_after_synthesis
from .schemas import ReusabilityRequest

__all__ = ["ReusabilityAgent", "ReusabilityExecution", "route_after_synthesis"]


class ReusabilityAgent(CoordinatorAgent):
    config_type = ReusabilityConfig
    trace_name = "reusability"
    agent_type = "reusability"
    actionable_gap = staticmethod(ReusabilityExecution.actionable)

    async def run(self, tools, request=None):
        if tools.budget_usage.tool_calls:
            raise ValueError("Use a fresh RepositoryToolset for the coordinator.")
        request = ReusabilityRequest.model_validate(request or ReusabilityRequest())
        request = request.model_copy(update={
            "targets": [repository_relative_path(target) for target in request.targets],
        })
        execution = ReusabilityExecution(self, tools, request)
        return await execution.run(recursion_limit=8 * self.config.max_rounds + 12)
