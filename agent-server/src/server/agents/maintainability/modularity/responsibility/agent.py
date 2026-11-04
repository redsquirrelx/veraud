"""Public responsibility-investigator binding; execution policy lives in execution.py."""

from config.agents import InvestigationConfig as ResponsibilityConfig

from .....runtimes.investigation.agent import InvestigationAgent
from .execution import ResponsibilityExecution
from .schemas import ResponsibilityRequest

__all__ = ["ResponsibilityAgent", "ResponsibilityExecution"]


class ResponsibilityAgent(InvestigationAgent):
    request_type = ResponsibilityRequest
    config_type = ResponsibilityConfig
    execution_type = ResponsibilityExecution
    trace_name = "responsibility"
    agent_type = "responsibility"
