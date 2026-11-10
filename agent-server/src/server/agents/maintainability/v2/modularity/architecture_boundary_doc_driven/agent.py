"""Documentary boundary agent with data-only external input."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import BoundaryConfig
from .execution import BoundaryExecution
from .schemas import AuditRequest


class ArchitectureBoundaryAgent(InvestigationAgent):
    request_type = AuditRequest
    config_type = BoundaryConfig
    execution_type = BoundaryExecution
    trace_name = "architecture-boundary"
    agent_type = "architecture_boundary"

    async def run(self, tools, request=None):
        return await super().run(tools, AuditRequest.model_validate({} if request is None else request))
