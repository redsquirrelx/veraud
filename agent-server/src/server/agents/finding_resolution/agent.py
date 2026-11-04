"""Investigation entry point; final resolution is intentionally not implemented."""

from pathlib import Path

from .config import FindingResolutionConfig
from .execution import FindingResolutionExecution
from .schemas import FindingResolutionRequest, FindingResolutionResult
from .state import FindingResolutionState


class FindingResolutionAgent:
    agent_type = "finding_resolution"
    request_type = FindingResolutionRequest
    result_type = FindingResolutionResult
    config_type = FindingResolutionConfig
    execution_type = FindingResolutionExecution

    def __init__(self, model, config: FindingResolutionConfig | None = None):
        self.model = model
        self.config = config or FindingResolutionConfig()

    async def run(self, request: FindingResolutionRequest, *, tools) -> FindingResolutionState:
        """Return collected investigations, not a final FindingResolutionResult."""
        if Path(request.repository_path).resolve() != Path(tools.accessible_snapshot.repository.root_path).resolve():
            raise ValueError("The toolset must belong to the requested repository_path.")
        identifiers = [finding.id for finding in request.findings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Original finding IDs must be unique.")
        execution = self.execution_type(self.model, self.config, tools, request)
        with execution.timing.stage("finding_resolution_investigation"):
            return await execution.graph.ainvoke(execution.initial_state(), {
                "recursion_limit": (2 * self.config.max_iterations + 4) * len(request.findings) + 4})
