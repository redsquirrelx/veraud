"""Architectural-boundary specialization of the shared investigation graph."""

from pathlib import Path

from config.agents import InvestigationConfig as BoundaryConfig

from .....runtimes.investigation.agent import InvestigationAgent, InvestigationExecution
from .schemas import AuditRequest


class _Execution(InvestigationExecution):
    trace_name = "architecture-boundary"
    tool_prefix = "boundary"
    prompt_directory = Path(__file__).parent / "prompts"


class ArchitectureBoundaryAgent(InvestigationAgent):
    request_type = AuditRequest
    config_type = BoundaryConfig
    execution_type = _Execution
    trace_name = "architecture-boundary"
    agent_type = "architecture_boundary"
