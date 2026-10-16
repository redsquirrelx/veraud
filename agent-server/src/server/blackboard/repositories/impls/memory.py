"""Thread-safe, process-local storage for auditable agent knowledge."""

from threading import Lock

from ...models import Assessment, BlackboardRecord, Evidence, Finding
from ..interface import BlackboardRepository


class MemoryBlackboardRepository(BlackboardRepository):
    """Keep detached records in memory for the lifetime of this instance."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._findings: dict[str, dict[str, Finding]] = {}
        self._evidence: dict[str, dict[str, Evidence]] = {}
        self._assessments: dict[str, dict[str, Assessment]] = {}

    def insert_finding(self, finding: Finding) -> str:
        return self._insert(self._findings, finding)

    def get_finding(self, audit_run_id: str, finding_id: str) -> Finding | None:
        return self._get(self._findings, audit_run_id, finding_id)

    def query_findings(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Finding]:
        return self._query(self._findings, audit_run_id, agent_execution_id)

    def insert_evidence(self, evidence: Evidence) -> str:
        return self._insert(self._evidence, evidence)

    def get_evidence(self, audit_run_id: str, evidence_id: str) -> Evidence | None:
        return self._get(self._evidence, audit_run_id, evidence_id)

    def insert_assessment(self, assessment: Assessment) -> str:
        return self._insert(self._assessments, assessment)

    def get_assessment(self, audit_run_id: str, assessment_id: str) -> Assessment | None:
        return self._get(self._assessments, audit_run_id, assessment_id)

    def query_assessments(
        self, audit_run_id: str, agent_execution_id: str | None = None,
    ) -> list[Assessment]:
        return self._query(self._assessments, audit_run_id, agent_execution_id)

    @staticmethod
    def _validate_identifier(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-blank string.")

    def _insert[T: BlackboardRecord](
        self, records: dict[str, dict[str, T]], record: T,
    ) -> str:
        # Own every nested container before retaining the caller's data.
        detached = record.model_copy(deep=True)
        self._validate_identifier(detached.run_id, "run_id")
        self._validate_identifier(detached.invocation_id, "invocation_id")
        self._validate_identifier(detached.id, "id")
        with self._lock:
            audit_records = records.get(detached.run_id)
            existing = audit_records.get(detached.id) if audit_records is not None else None
            if existing is not None:
                if existing.model_dump(mode="json") != detached.model_dump(mode="json"):
                    raise ValueError(
                        f"Conflicting {type(record).__name__} ID {detached.id!r} "
                        f"in audit {detached.run_id!r}.",
                    )
                return existing.id
            if audit_records is None:
                audit_records = {}
                records[detached.run_id] = audit_records
            audit_records[detached.id] = detached
            return detached.id

    def _get[T: BlackboardRecord](
        self, records: dict[str, dict[str, T]], audit_run_id: str, record_id: str,
    ) -> T | None:
        self._validate_identifier(audit_run_id, "audit_run_id")
        self._validate_identifier(record_id, "record_id")
        with self._lock:
            record = records.get(audit_run_id, {}).get(record_id)
            return record.model_copy(deep=True) if record is not None else None

    def _query[T: BlackboardRecord](
        self,
        records: dict[str, dict[str, T]],
        audit_run_id: str,
        agent_execution_id: str | None,
    ) -> list[T]:
        self._validate_identifier(audit_run_id, "audit_run_id")
        if agent_execution_id is not None:
            self._validate_identifier(agent_execution_id, "agent_execution_id")
        with self._lock:
            return [
                record.model_copy(deep=True)
                for record in records.get(audit_run_id, {}).values()
                if agent_execution_id is None or record.invocation_id == agent_execution_id
            ]
