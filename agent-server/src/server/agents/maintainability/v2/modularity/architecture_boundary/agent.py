"""Minimal architectural-boundary agent with only its initial graph node."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import BoundaryConfig
from .execution import BoundaryExecution
from .schemas import AuditRequest


class ArchitectureBoundaryAgent(InvestigationAgent):
    request_type = AuditRequest
    config_type = BoundaryConfig
    execution_type = BoundaryExecution
    trace_name = "architecture-boundary"
    agent_type = "architecture_boundary"
