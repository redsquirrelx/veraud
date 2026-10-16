"""Public adaptability binding; inspection, validation and graph policy live in execution.py."""

from .....runtimes.investigation.agent import InvestigationAgent
from .config import ComponentAdaptabilityConfig
from .execution import ComponentAdaptabilityExecution
from .schemas import ComponentAdaptabilityRequest

__all__ = ["ComponentAdaptabilityAgent", "ComponentAdaptabilityExecution"]


class ComponentAdaptabilityAgent(InvestigationAgent):
    request_type = ComponentAdaptabilityRequest
    config_type = ComponentAdaptabilityConfig
    execution_type = ComponentAdaptabilityExecution
    trace_name = "component-adaptability"
    agent_type = "component-adaptability"
