"""Public dependency-impact binding; source validation lives in execution.py."""

from .....runtimes.investigation.agent import InvestigationAgent
from .config import DependencyImpactConfig
from .execution import DependencyImpactExecution
from .schemas import DependencyImpactRequest

__all__ = ["DependencyImpactAgent", "DependencyImpactExecution"]


class DependencyImpactAgent(InvestigationAgent):
    request_type = DependencyImpactRequest
    config_type = DependencyImpactConfig
    execution_type = DependencyImpactExecution
    trace_name = "dependency-impact"
    agent_type = "dependency_impact"
