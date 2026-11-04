"""Public abstraction-investigator binding; technical analysis lives in execution.py."""

from .....runtimes.investigation.agent import InvestigationAgent
from .config import AbstractionConfig
from .execution import AbstractionExecution
from .schemas import AbstractionRequest

__all__ = ["AbstractionAgent", "AbstractionExecution"]


class AbstractionAgent(InvestigationAgent):
    request_type = AbstractionRequest
    config_type = AbstractionConfig
    execution_type = AbstractionExecution
    trace_name = "abstraction"
    agent_type = "abstraction"
