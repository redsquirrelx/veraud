"""Documentary test-isolation agent with data-only external input."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import TestIsolationConfig
from .execution import TestIsolationExecution
from .schemas import AuditRequest


class TestIsolationAgent(InvestigationAgent):
    request_type = AuditRequest
    config_type = TestIsolationConfig
    execution_type = TestIsolationExecution
    trace_name = "test_isolation"
    agent_type = "test_isolation"

    async def run(self, tools, request=None):
        return await super().run(tools, AuditRequest.model_validate({} if request is None else request))
