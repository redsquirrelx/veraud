"""Bounded abstraction-purpose investigator; planning is implemented."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import AbstractionConfig
from .execution import AbstractionExecution
from .schemas import AbstractionRequest


class AbstractionAgent(InvestigationAgent):
    request_type = AbstractionRequest
    config_type = AbstractionConfig
    execution_type = AbstractionExecution
    trace_name = "abstraction-v2-investigator"
    agent_type = "abstraction"

    async def run(self, tools, request=None):
        request = self.request_type() if request is None else self.request_type.model_validate(request)
        return await super().run(tools, request)
