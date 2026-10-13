"""Build-time state; the public snapshot itself is immutable."""

import hashlib
import posixpath

from .schemas import (
    AnalysisIssue,
    ArchitectureSignal,
    DependencyRecord,
    EntrypointRecord,
    EvidenceRecord,
    InfrastructureRecord,
    ProjectRecord,
    RelationshipRecord,
    SourceFile,
    SymbolRecord,
    TechnologyRecord,
    TestConfiguration,
)


def create_identifier(entity_kind: str, *identity_parts: object) -> str:
    identity = "\0".join(str(part) for part in identity_parts)
    return f"{entity_kind}:{hashlib.sha256(identity.encode()).hexdigest()[:24]}"


class AnalysisContext:
    def __init__(
        self,
        files: tuple[SourceFile, ...],
        issues: list[AnalysisIssue],
        directory_paths: tuple[str, ...] = (),
    ):
        self.files = {source_file.path: source_file for source_file in files}
        self.issues = issues
        self.directory_paths = directory_paths
        self.projects: list[ProjectRecord] = []
        self.symbols: list[SymbolRecord] = []
        self.technologies: list[TechnologyRecord] = []
        self.dependencies: list[DependencyRecord] = []
        self.relationships: list[RelationshipRecord] = []
        self.architecture_signals: list[ArchitectureSignal] = []
        self.entrypoints: list[EntrypointRecord] = []
        self.infrastructure: list[InfrastructureRecord] = []
        self.testing: list[TestConfiguration] = []
        self.evidence: dict[str, EvidenceRecord] = {}
        self.configuration: dict[str, dict] = {}
        self.python_trees: dict[str, object] = {}
        self.javascript_trees: dict[str, object] = {}

    def add_evidence(
        self,
        source_file: SourceFile,
        rule: str,
        start_line: int | None = None,
        end_line: int | None = None,
        configuration_key: str | None = None,
    ) -> str:
        evidence_id = create_identifier(
            "evidence", source_file.path, rule, start_line, end_line, configuration_key
        )
        self.evidence[evidence_id] = EvidenceRecord(
            id=evidence_id,
            file_id=source_file.id,
            path=source_file.path,
            rule=rule,
            start_line=start_line,
            end_line=end_line,
            configuration_key=configuration_key,
        )
        return evidence_id

    def add_issue(self, path: str, category: str, message: str) -> None:
        self.issues.append(AnalysisIssue(path=path, category=category, message=message))

    def project_for_path(self, path: str) -> ProjectRecord:
        candidates = [
            project
            for project in self.projects
            if project.path == "."
            or path == project.path
            or path.startswith(project.path + "/")
        ]
        return max(
            candidates,
            key=lambda project: len(project.path) if project.path != "." else 0,
        )

    def processed_files(self) -> tuple[SourceFile, ...]:
        return tuple(
            source_file
            for source_file in self.files.values()
            if source_file.status == "processed"
        )

    def source_file_for_id(self, file_id: str) -> SourceFile:
        return next(
            source_file
            for source_file in self.files.values()
            if source_file.id == file_id
        )


def normalize_dependency_name(name: str, ecosystem: str) -> str:
    return (
        name.lower().replace("_", "-").replace(".", "-")
        if ecosystem == "python"
        else name
    )


def containing_directory(path: str) -> str:
    return posixpath.dirname(path) or "."
