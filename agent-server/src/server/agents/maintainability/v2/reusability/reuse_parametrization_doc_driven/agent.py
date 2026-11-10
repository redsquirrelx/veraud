"""Documentary reuse-parametrization investigator for maintainability V2."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import ReuseParametrizationConfig
from .execution import ReuseParametrizationDocDrivenExecution
from .schemas import (
    ReuseParametrizationDocDrivenRequest,
    ReuseParametrizationDocDrivenResult,
)


class ReuseParametrizationDocDrivenAgent(InvestigationAgent):
    request_type = ReuseParametrizationDocDrivenRequest
    result_type = ReuseParametrizationDocDrivenResult
    config_type = ReuseParametrizationConfig
    execution_type = ReuseParametrizationDocDrivenExecution
    agent_type = "reuse_parametrization_doc_driven"
    trace_name = "reuse-parametrization-doc-driven"
