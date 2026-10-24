"""Storage boundary used by blackboard implementations, independent of agents."""

from abc import ABC, abstractmethod

from ..models import Assessment, Evidence, Finding


class BlackboardRepository(ABC):
    """Append-only persistence contract for knowledge records.

    Insertions atomically compare (run_id, entity type, id). New records are
    retained unchanged and return their id. Identical model_dump(mode="json")
    data is an idempotent retry and returns the existing id. Different data for
    the same identity raises ValueError without modifying the stored record.
    This guarantee also applies to concurrent insertions.

    All reads are scoped to audit_run_id (model.run_id); optional execution
    filters match model.invocation_id, not agent_id. Never search another audit
    when an ID or reference is missing. Missing reads return None or [], as
    appropriate; queries return each match once with unspecified ordering.

    Capture deep copies on insertion and return deep copies on reads, preserving
    every field, including nested details, references and producer metadata.
    Empty/whitespace-only run, execution or record IDs raise ValueError; other
    identifiers are matched exactly without normalization.

    The repository stores references without resolving them or interpreting
    findings, assessments or audit-specific policy. Blackboard owns knowledge
    publication semantics; the repository owns storage and concurrency.
    """

    @abstractmethod
    def insert_finding(self, finding: Finding) -> str:
        """Atomically retain a finding or compare it with the existing record."""
        raise NotImplementedError

    @abstractmethod
    def get_finding(self, audit_run_id: str, finding_id: str) -> Finding | None:
        """Return a detached finding belonging to this audit, or None."""
        raise NotImplementedError

    @abstractmethod
    def query_findings(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Finding]:
        """Return detached findings scoped to the audit and optional execution."""
        raise NotImplementedError

    @abstractmethod
    def insert_evidence(self, evidence: Evidence) -> str:
        """Atomically retain evidence or compare it with the existing record."""
        raise NotImplementedError

    @abstractmethod
    def get_evidence(self, audit_run_id: str, evidence_id: str) -> Evidence | None:
        """Return detached evidence belonging to this audit, or None."""
        raise NotImplementedError

    @abstractmethod
    def query_evidence(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Evidence]:
        """Return detached evidence scoped to the audit and optional execution."""
        raise NotImplementedError

    @abstractmethod
    def insert_assessment(self, assessment: Assessment) -> str:
        """Atomically retain an assessment or compare it with the existing record."""
        raise NotImplementedError

    @abstractmethod
    def get_assessment(self, audit_run_id: str, assessment_id: str) -> Assessment | None:
        """Return a detached assessment belonging to this audit, or None."""
        raise NotImplementedError

    @abstractmethod
    def query_assessments(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Assessment]:
        """Return detached assessments scoped to the audit and optional execution."""
        raise NotImplementedError
