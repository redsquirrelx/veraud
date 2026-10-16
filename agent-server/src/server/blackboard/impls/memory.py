"""Agent-facing blackboard backed by an in-memory repository."""

from ..interface import Blackboard
from ..models import Assessment, Evidence, Finding
from ..repositories.impls.memory import MemoryBlackboardRepository
from ..repositories.interface import BlackboardRepository


class MemoryBlackboard(Blackboard):
    """Publish knowledge through a repository, using instance-local memory by default."""

    def __init__(self, repository: BlackboardRepository | None = None) -> None:
        self._repository = repository if repository is not None else MemoryBlackboardRepository()

    def publish_finding(self, finding: Finding) -> str:
        return self._repository.insert_finding(finding)

    def get_finding(self, audit_run_id: str, finding_id: str) -> Finding | None:
        return self._repository.get_finding(audit_run_id, finding_id)

    def query_findings(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Finding]:
        return self._repository.query_findings(audit_run_id, agent_execution_id)

    def publish_evidence(self, evidence: Evidence) -> str:
        return self._repository.insert_evidence(evidence)

    def get_evidence(self, audit_run_id: str, evidence_id: str) -> Evidence | None:
        return self._repository.get_evidence(audit_run_id, evidence_id)

    def publish_assessment(self, assessment: Assessment) -> str:
        return self._repository.insert_assessment(assessment)

    def get_assessment(self, audit_run_id: str, assessment_id: str) -> Assessment | None:
        return self._repository.get_assessment(audit_run_id, assessment_id)

    def query_assessments(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Assessment]:
        return self._repository.query_assessments(audit_run_id, agent_execution_id)
