"""Public maintainability-manager lifecycle; hierarchy policy lives in execution.py."""

from typing import TYPE_CHECKING

from ....runtimes.coordination.execution import CoordinatorAgent
from ....runtimes.repository.access import repository_relative_path
from .config import MaintainabilityConfig
from .execution import MaintainabilityManagerExecution, coverage_router
from .schemas import MaintainabilityRequest

if TYPE_CHECKING:
    from ....blackboard.identity import AuditIdentity
    from ....blackboard.interface import Blackboard

__all__ = ["MaintainabilityManagerAgent", "MaintainabilityManagerExecution", "coverage_router"]


class MaintainabilityManagerAgent(CoordinatorAgent):
    config_type = MaintainabilityConfig
    trace_name = "maintainability-manager"
    agent_type = "maintainability_manager"

    def __init__(self, model, config=None, *, tracing_backend=None, coordinator_factory=None, provider_pacer=None,
                 blackboard: "Blackboard | None" = None, audit_identity: "AuditIdentity | None" = None):
        super().__init__(
            model, config, tracing_backend=tracing_backend,
            investigator_factory=coordinator_factory, provider_pacer=provider_pacer,
            blackboard=blackboard, audit_identity=audit_identity,
        )

    async def run(self, tools, request=None):
        if tools.budget_usage.tool_calls:
            raise ValueError("Use a fresh RepositoryToolset for the manager.")
        request = MaintainabilityRequest.model_validate(request or MaintainabilityRequest())
        request = request.model_copy(update={
            "targets": [repository_relative_path(target) for target in request.targets],
            "dimension_targets": {
                dimension: [repository_relative_path(target) for target in targets]
                for dimension, targets in request.dimension_targets.items()
            },
        })
        execution = MaintainabilityManagerExecution(self, tools, request)
        return await execution.run(recursion_limit=8 * self.config.max_rounds + 16)
