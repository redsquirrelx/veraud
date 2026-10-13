"""Public contracts shared by extractors, consumers and query results."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DetectionKind = Literal["declared", "observed", "inferred"]
FileStatus = Literal[
    "processed",
    "excluded",
    "binary",
    "too_large",
    "file_limit",
    "memory_limit",
    "unreadable",
    "invalid_encoding",
]


class AnalysisModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RepositoryAnalysisInput(AnalysisModel):
    root_path: str
    max_files: int = Field(default=5000, ge=1)
    max_depth: int = Field(default=30, ge=0)
    max_file_bytes: int = Field(default=2_000_000, ge=1)
    max_total_bytes: int = Field(default=64_000_000, ge=1)


class RepositoryIdentity(AnalysisModel):
    name: str
    root_path: str
    commit: str | None = None
    snapshot_hash: str
    extractor_version: str = "1"
    python_version: str


class EvidenceRecord(AnalysisModel):
    id: str
    file_id: str
    path: str
    rule: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    configuration_key: str | None = None


class SourceFile(AnalysisModel):
    id: str
    path: str
    project_id: str
    language: str
    module_name: str | None = None
    size_bytes: int = Field(ge=0)
    status: FileStatus
    content_hash: str | None = None
    line_count: int | None = None
    content: str | None = Field(default=None, repr=False)


class ProjectRecord(AnalysisModel):
    id: str
    path: str
    name: str
    ecosystem: str
    manifest_paths: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class DirectoryRecord(AnalysisModel):
    id: str
    path: str
    project_id: str
    kind: Literal["directory", "python_package", "namespace_candidate"]


class SymbolRecord(AnalysisModel):
    id: str
    file_id: str
    project_id: str
    name: str
    qualified_name: str
    kind: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    signature: str | None = None
    parent_symbol_id: str | None = None
    base_names: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class TechnologyRecord(AnalysisModel):
    id: str
    project_id: str
    name: str
    kind: Literal["language", "framework", "runtime", "tool"]
    detection: DetectionKind
    version_constraint: str | None = None
    resolved_version: str | None = None
    evidence_ids: tuple[str, ...] = ()


class DependencyRecord(AnalysisModel):
    id: str
    project_id: str
    name: str
    ecosystem: str
    scope: str
    detection: DetectionKind
    version_constraint: str | None = None
    resolved_versions: tuple[str, ...] = ()
    environment_marker: str | None = None
    evidence_ids: tuple[str, ...] = ()


class RelationshipRecord(AnalysisModel):
    id: str
    project_id: str
    source_id: str
    target_id: str | None
    kind: str
    specifier: str
    resolution: Literal["internal", "external", "builtin", "unresolved", "dynamic"]
    evidence_ids: tuple[str, ...] = ()


class ArchitectureSignal(AnalysisModel):
    id: str
    project_id: str
    kind: str
    name: str
    description: str
    detection: DetectionKind
    entity_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()


class EntrypointRecord(AnalysisModel):
    id: str
    project_id: str
    kind: Literal[
        "application", "cli", "http_endpoint", "framework_page", "public_api", "service"
    ]
    name: str
    target: str
    file_id: str | None = None
    symbol_id: str | None = None
    http_method: str | None = None
    route: str | None = None
    detection: DetectionKind
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class InfrastructureRecord(AnalysisModel):
    id: str
    project_id: str
    kind: Literal["container", "database", "external_service"]
    name: str
    image: str | None = None
    build_context: str | None = None
    ports: tuple[str, ...] = ()
    detection: DetectionKind
    evidence_ids: tuple[str, ...] = ()


class TestConfiguration(AnalysisModel):
    id: str
    project_id: str
    framework: str | None
    file_paths: tuple[str, ...] = ()
    configuration_paths: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    detection: DetectionKind
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = (
        "Test files are naming-based candidates; framework ownership and execution coverage are not inferred.",
    )


class AnalysisIssue(AnalysisModel):
    path: str
    category: str
    message: str


class AnalysisCoverage(AnalysisModel):
    discovered_files: int
    processed_files: int
    retained_bytes: int
    supported_source_languages: tuple[str, ...] = ("python", "javascript", "typescript")
    unsupported_source_languages: tuple[str, ...] = ()
    issues: tuple[AnalysisIssue, ...] = ()
    limitations: tuple[str, ...] = ()


class RepositorySnapshot(AnalysisModel):
    schema_version: str = "1"
    repository: RepositoryIdentity
    projects: tuple[ProjectRecord, ...]
    files: tuple[SourceFile, ...]
    directories: tuple[DirectoryRecord, ...]
    symbols: tuple[SymbolRecord, ...]
    technologies: tuple[TechnologyRecord, ...]
    dependencies: tuple[DependencyRecord, ...]
    relationships: tuple[RelationshipRecord, ...]
    architecture_signals: tuple[ArchitectureSignal, ...]
    entrypoints: tuple[EntrypointRecord, ...]
    infrastructure: tuple[InfrastructureRecord, ...]
    testing: tuple[TestConfiguration, ...]
    evidence: tuple[EvidenceRecord, ...]
    coverage: AnalysisCoverage


class QueryPage[Item](AnalysisModel):
    items: tuple[Item, ...]
    total: int
    offset: int
    limit: int


class SourceExcerpt(AnalysisModel):
    file_id: str
    path: str
    start_line: int
    end_line: int
    content: str
    content_hash: str


class TextSearchMatch(AnalysisModel):
    file_id: str
    path: str
    line: int
    text: str


class RepositoryOverview(AnalysisModel):
    repository: RepositoryIdentity
    project_count: int
    file_count: int
    symbol_count: int
    dependency_count: int
    relationship_count: int
    technologies: tuple[TechnologyRecord, ...]
    entrypoint_count: int
    infrastructure_count: int
    test_configuration_count: int
    coverage: AnalysisCoverage
