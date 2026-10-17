"""Architectural-boundary specialization of the shared investigation graph."""

from config.agents import InvestigationConfig as BoundaryConfig

from .....runtimes.investigation.agent import InvestigationAgent
from .execution import BoundaryExecution
from .schemas import AuditRequest


class ArchitectureBoundaryAgent(InvestigationAgent):
    request_type = AuditRequest
    config_type = BoundaryConfig
    execution_type = BoundaryExecution
    trace_name = "architecture-boundary"
    agent_type = "architecture_boundary"
