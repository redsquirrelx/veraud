"""V2 investigator through documentary planning and source-backed investigation."""

from server.runtimes.investigation.agent import InvestigationAgent

from .config import ReuseOpportunityConfig
from .execution import ReuseOpportunityExecution
from .schemas import (
    ReuseOpportunityDocDrivenRequest,
    ReuseOpportunityDocDrivenResult,
)


class ReuseOpportunityDocDrivenAgent(InvestigationAgent):
    """V2 investigator whose current graph intentionally ends after planning."""

    request_type = ReuseOpportunityDocDrivenRequest
    result_type = ReuseOpportunityDocDrivenResult
    config_type = ReuseOpportunityConfig
    execution_type = ReuseOpportunityExecution
    agent_type = "reuse_opportunity_doc_driven"
    trace_name = "reuse-opportunity-doc-driven-v2-investigator"
