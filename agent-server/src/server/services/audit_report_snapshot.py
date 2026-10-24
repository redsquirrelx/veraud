"""Build reports from portable Blackboard knowledge without accessing live audits."""

from pydantic import BaseModel, Field, model_validator

from ..agents.audit_report import (
    AuditReportAgent,
    AuditReportRequest,
    SoftwareAuditReport,
)
from ..agents.audit_report.input_validation import validate_extensions
from ..blackboard.impls.memory import MemoryBlackboard
from ..blackboard.models import Assessment, Evidence, Finding


class BlackboardSnapshot(BaseModel):
    """Knowledge required by the report builder; lifecycle metadata is optional."""

    run_id: str = Field(min_length=1, pattern=r"\S")
    evidence: list[Evidence]
    findings: list[Finding]
    assessments: list[Assessment]

    @model_validator(mode="after")
    def validate_identity(self):
        for records in (self.evidence, self.findings, self.assessments):
            if any(record.run_id != self.run_id for record in records):
                raise ValueError("All Blackboard records must belong to the snapshot's run_id.")
            if len({record.id for record in records}) != len(records):
                raise ValueError("Duplicate Blackboard record IDs are not allowed.")
        validate_extensions({"evidence": self.evidence, "findings": self.findings, "assessments": self.assessments})
        return self


async def report_from_snapshot(snapshot: BlackboardSnapshot) -> SoftwareAuditReport:
    board = MemoryBlackboard()
    for records, publish in ((snapshot.evidence, board.publish_evidence),
            (snapshot.findings, board.publish_finding), (snapshot.assessments, board.publish_assessment)):
        for record in records:
            publish(record)
    return await AuditReportAgent(blackboard=board).run(AuditReportRequest(run_id=snapshot.run_id))
