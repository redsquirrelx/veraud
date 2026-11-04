from abc import ABC, abstractmethod

from .models import Assessment, Evidence, Finding


class Blackboard(ABC):
    """Agent-facing contract for publishing and consulting auditable knowledge.

    This layer defines knowledge-sharing rules, reference scope and producer
    provenance. Implementations delegate storage to BlackboardRepository from
    repositories.interface, which owns atomic insertion, duplicate detection,
    isolation and detached reads. Agents depend on this interface, not on a
    repository or its storage technology.

    Scope and provenance:
        audit_run_id corresponds to the existing models' run_id;
        agent_execution_id corresponds to invocation_id, not agent_id.
        Every read MUST filter by run_id before looking up IDs or executions.
        References in finding_ids, evidence_ids and assessment_ids identify
        blackboard records in that same audit, never another audit's records.
        Forward references may remain unresolved; they MUST NOT fall back to
        looking up records in other audits.

    Publication and retries:
        The identity of a record is (run_id, entity type, id). Publication uses
        the repository's atomic insert-or-compare, including concurrent retries.
        A new record returns its supplied id without changing its provenance.
        An existing record with identical model_dump(mode="json") data returns
        the same id without writing again. Any difference raises ValueError and
        leaves the original intact. Retry the original record, retaining its id,
        created_at and execution metadata; rebuilding it is not an identical retry.

    Preservation:
        Implementations MUST retain all model fields, including details and
        referenced IDs, without rewriting agent or execution identities.
        Publication MUST capture a detached copy, and reads MUST return detached
        copies: mutating nested containers MUST NOT alter stored knowledge.
        Query results contain every matching record once; ordering is unspecified.
        Empty/whitespace-only scope, execution or record identifiers raise
        ValueError; identifiers are otherwise matched exactly, without trimming.

    Storage, authorization and report construction belong to consumers and
    implementations; this interface has no dependency on an audit dimension.
    """

    @abstractmethod
    def publish_finding(self, finding: Finding) -> str:
        """Publish in finding.run_id; return its id under the shared retry policy."""
        raise NotImplementedError

    @abstractmethod
    def get_finding(self, audit_run_id: str, finding_id: str) -> Finding | None:
        """Return a finding in this audit, or None, even if its ID exists elsewhere."""
        raise NotImplementedError

    @abstractmethod
    def query_findings(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Finding]:
        """List this audit's findings, optionally filtered by invocation_id.

        None selects all producing executions within this audit. Return [] when
        no records match; never include findings from another audit.
        """
        raise NotImplementedError

    @abstractmethod
    def publish_evidence(self, evidence: Evidence) -> str:
        """Publish in evidence.run_id; return its id under the shared retry policy."""
        raise NotImplementedError

    @abstractmethod
    def get_evidence(self, audit_run_id: str, evidence_id: str) -> Evidence | None:
        """Return evidence in this audit, or None, even if its ID exists elsewhere."""
        raise NotImplementedError

    @abstractmethod
    def query_evidence(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Evidence]:
        """List all evidence in this audit, optionally filtered by producing execution.

        Includes records not yet referenced by a finding or assessment.
        """
        raise NotImplementedError

    @abstractmethod
    def publish_assessment(self, assessment: Assessment) -> str:
        """Publish in assessment.run_id; return its id under the shared retry policy."""
        raise NotImplementedError

    @abstractmethod
    def get_assessment(self, audit_run_id: str, assessment_id: str) -> Assessment | None:
        """Return an assessment in this audit, or None if it is not in this audit."""
        raise NotImplementedError

    @abstractmethod
    def query_assessments(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Assessment]:
        """List this audit's assessments, optionally filtered by invocation_id.

        None selects all producing executions within this audit. Return [] when
        no records match, including audits completed without assessments.
        """
        raise NotImplementedError
