"""Public reuse-opportunity binding; comparison and graph policy live in execution.py."""

from .....runtimes.investigation.agent import InvestigationAgent
from .config import ReuseOpportunityConfig
from .execution import ReuseOpportunityExecution
from .schemas import ReuseOpportunityRequest

__all__ = ["ReuseOpportunityAgent", "ReuseOpportunityExecution"]


class ReuseOpportunityAgent(InvestigationAgent):
    request_type = ReuseOpportunityRequest
    config_type = ReuseOpportunityConfig
    execution_type = ReuseOpportunityExecution
    trace_name = "reuse-opportunity"
    agent_type = "reuse-opportunity"
