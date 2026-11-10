"""Documentary responsibility agent with data-only external input."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import ResponsibilityConfig
from .execution import ResponsibilityExecution
from .schemas import AuditRequest


class ResponsibilityAgent(InvestigationAgent):
    request_type = AuditRequest
    config_type = ResponsibilityConfig
    execution_type = ResponsibilityExecution
    trace_name = "responsibility"
    agent_type = "responsibility"

    async def run(self, tools, request=None):
        return await super().run(tools, AuditRequest.model_validate({} if request is None else request))
