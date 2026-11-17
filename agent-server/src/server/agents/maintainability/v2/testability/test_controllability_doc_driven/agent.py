"""Documentary test-controllability agent with data-only external input."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import TestControllabilityConfig
from .execution import TestControllabilityExecution
from .schemas import AuditRequest


class TestControllabilityAgent(InvestigationAgent):
    request_type = AuditRequest
    config_type = TestControllabilityConfig
    execution_type = TestControllabilityExecution
    trace_name = "test_controllability"
    agent_type = "test_controllability"

    async def run(self, tools, request=None):
        return await super().run(tools, AuditRequest.model_validate({} if request is None else request))
