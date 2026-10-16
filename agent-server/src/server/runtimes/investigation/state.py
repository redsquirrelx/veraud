from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from .schemas import (
    AuditResult,
    Evaluation,
    EvidenceReference,
    Hypothesis,
    InvestigationPlan,
    Review,
)


class InvestigationState(TypedDict):
    repository_id: str
    commit: str | None
    objective: str
    architectural_context: str
    criteria: list[dict]
    plan: InvestigationPlan | None
    hypotheses: list[Hypothesis]
    messages: Annotated[list[AnyMessage], add_messages]
    evidence: list[EvidenceReference]
    evaluation: Evaluation | None
    missing_information: list[str]
    review: Review | None
    iterations: int
    model_calls: int
    tool_calls: int
    termination_reason: str
    limitations: list[str]
    limits: dict
    result: AuditResult
