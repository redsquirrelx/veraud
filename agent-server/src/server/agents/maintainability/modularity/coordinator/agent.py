"""Public modularity-coordinator lifecycle; graph policy lives in execution.py."""

from config.agents import CoordinatorConfig as ModularityConfig

from .....runtimes.coordination.execution import CoordinatorAgent
from .execution import (
    ModularityExecution,
    ModularitySynthesisExecution,
    route_after_synthesis,
)
from .schemas import ModularityRequest

__all__ = ["ModularityAgent", "ModularityExecution", "ModularitySynthesisExecution", "route_after_synthesis"]


class ModularityAgent(CoordinatorAgent):
    config_type = ModularityConfig
    trace_name = "modularity"
    agent_type = "modularity"

    async def run(self, tools, request=None):
        if tools.budget_usage.tool_calls:
            raise ValueError("Use a fresh RepositoryToolset for the coordinator.")
        execution = ModularityExecution(self, tools, request or ModularityRequest())
        return await execution.run(recursion_limit=12 * self.config.max_rounds + 20)
