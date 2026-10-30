"""Public binding for the shared, read-only cognitive investigation graph."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import CodeComprehensionConfig
from .execution import CodeComprehensionExecution
from .schemas import CodeComprehensionRequest


class CodeComprehensionAgent(InvestigationAgent):
    request_type = CodeComprehensionRequest
    config_type = CodeComprehensionConfig
    execution_type = CodeComprehensionExecution
    trace_name = "code-comprehension"
    agent_type = "code_comprehension"
