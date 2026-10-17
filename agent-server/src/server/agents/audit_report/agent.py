"""Stateless, blackboard-only audit document agent with a deterministic graph."""

from datetime import UTC, datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ...blackboard.interface import Blackboard
from .execution import ReportExecution
from .schemas import AuditReportRequest, SoftwareAuditReport


class ReportState(TypedDict, total=False):
    records: dict
    report: SoftwareAuditReport


class AuditReportAgent:
    agent_type = "audit_report"
    trace_name = "audit-report"
    input_schema = AuditReportRequest
    output_schema = SoftwareAuditReport

    def __init__(self, *, blackboard: Blackboard):
        self.blackboard = blackboard

    async def run(self, request: AuditReportRequest) -> SoftwareAuditReport:
        request = AuditReportRequest.model_validate(request)
        execution = ReportExecution(self.blackboard, request.run_id, datetime.now(UTC))
        graph = StateGraph(ReportState)
        graph.add_node("read_blackboard", execution.read_blackboard)
        graph.add_node("assemble_report", execution.assemble_report)
        graph.add_node("validate_traceability", execution.validate_traceability)
        graph.add_edge(START, "read_blackboard")
        graph.add_edge("read_blackboard", "assemble_report")
        graph.add_edge("assemble_report", "validate_traceability")
        graph.add_edge("validate_traceability", END)
        result = await graph.compile().ainvoke({})
        return result["report"]
