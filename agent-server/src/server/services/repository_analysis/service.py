"""Build a self-contained repository snapshot in memory, without model calls."""

import asyncio
import hashlib
import json
import platform
import posixpath
import subprocess
from pathlib import Path

from .architecture import extract_architecture_signals
from .context import AnalysisContext, create_identifier
from .entrypoints import extract_entrypoints
from .infrastructure import extract_infrastructure
from .inventory import scan_repository
from .manifests import (
    extract_dependency_technologies,
    extract_locked_versions,
    extract_manifest_facts,
    identify_projects,
    read_project_configuration,
)
from .relationships import extract_import_relationships
from .schemas import (
    AnalysisCoverage,
    DirectoryRecord,
    RepositoryAnalysisInput,
    RepositoryIdentity,
    RepositorySnapshot,
)
from .source_code import extract_source_code
from .testing import extract_testing

UNSUPPORTED_SOURCE_LANGUAGES = frozenset(
    {
        "go",
        "rust",
        "java",
        "csharp",
        "c",
        "cpp",
        "ruby",
        "php",
        "kotlin",
        "swift",
        "vue",
        "svelte",
    }
)


class RepositoryChangedError(RuntimeError):
    """The retained files changed while the snapshot was being constructed."""


def repository_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and len(commit) == 40 else None


def build_directories(context: AnalysisContext) -> tuple[DirectoryRecord, ...]:
    directory_paths = {".", *context.directory_paths}
    for file_path in context.files:
        directory = posixpath.dirname(file_path)
        while directory:
            directory_paths.add(directory)
            directory = posixpath.dirname(directory)
    directories = []
    for directory_path in sorted(directory_paths):
        package_marker = (
            directory_path + "/" if directory_path != "." else ""
        ) + "__init__.py"
        has_python_sources = any(
            source_file.language == "python"
            and posixpath.dirname(source_file.path) == directory_path
            for source_file in context.files.values()
        )
        kind = (
            "python_package"
            if package_marker in context.files
            else "namespace_candidate"
            if has_python_sources
            else "directory"
        )
        directories.append(
            DirectoryRecord(
                id=create_identifier("directory", directory_path),
                path=directory_path,
                project_id=context.project_for_path(directory_path).id,
                kind=kind,
            )
        )
    return tuple(directories)


def sorted_unique_records(records):
    records_by_id = {record.id: record for record in records}
    return tuple(records_by_id[identifier] for identifier in sorted(records_by_id))


def validate_snapshot_references(snapshot: RepositorySnapshot):
    entity_ids = {
        entity.id
        for collection in (
            snapshot.projects,
            snapshot.files,
            snapshot.directories,
            snapshot.symbols,
            snapshot.dependencies,
            snapshot.technologies,
            snapshot.infrastructure,
            snapshot.entrypoints,
            snapshot.testing,
        )
        for entity in collection
    }
    evidence_ids = {evidence.id for evidence in snapshot.evidence}
    project_ids = {project.id for project in snapshot.projects}
    file_index = {source_file.id: source_file for source_file in snapshot.files}
    for collection in (
        snapshot.files,
        snapshot.directories,
        snapshot.symbols,
        snapshot.technologies,
        snapshot.dependencies,
        snapshot.relationships,
        snapshot.architecture_signals,
        snapshot.entrypoints,
        snapshot.infrastructure,
        snapshot.testing,
    ):
        for entity in collection:
            if entity.project_id not in project_ids:
                raise ValueError(f"Unknown project reference: {entity.project_id}")
            if any(
                evidence_id not in evidence_ids
                for evidence_id in getattr(entity, "evidence_ids", ())
            ):
                raise ValueError(f"Unknown evidence reference on {entity.id}")
    for relationship in snapshot.relationships:
        if (
            relationship.source_id not in entity_ids
            or relationship.target_id is not None
            and relationship.target_id not in entity_ids
        ):
            raise ValueError(f"Unknown relationship endpoint: {relationship.id}")
    for signal in snapshot.architecture_signals:
        if any(entity_id not in entity_ids for entity_id in signal.entity_ids):
            raise ValueError(f"Unknown architecture entity reference: {signal.id}")
    for evidence in snapshot.evidence:
        source_file = file_index.get(evidence.file_id)
        if source_file is None:
            raise ValueError(f"Unknown evidence file: {evidence.id}")
        if evidence.start_line is not None and not (
            1
            <= evidence.start_line
            <= (evidence.end_line or evidence.start_line)
            <= (source_file.line_count or 0)
        ):
            raise ValueError(
                f"Evidence range is outside retained source: {evidence.id}"
            )


class RepositoryAnalysisService:
    async def analyze(
        self, options: RepositoryAnalysisInput | str | Path
    ) -> RepositorySnapshot:
        """Analyze on a worker thread; retain source and facts only in the result."""
        if not isinstance(options, RepositoryAnalysisInput):
            options = RepositoryAnalysisInput(root_path=str(options))
        return await asyncio.to_thread(self.analyze_sync, options)

    def analyze_sync(
        self, options: RepositoryAnalysisInput | str | Path
    ) -> RepositorySnapshot:
        """Synchronous entry for scripts and callers without an event loop."""
        if not isinstance(options, RepositoryAnalysisInput):
            options = RepositoryAnalysisInput(root_path=str(options))
        root = Path(options.root_path).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Repository root is not a directory: {root}")
        initial_commit = repository_commit(root)
        files, issues, directory_paths = scan_repository(root, options)
        context = AnalysisContext(files, issues, directory_paths)
        read_project_configuration(context)
        identify_projects(context, root.name)
        # Each stage consumes the same retained inventory and adds provenance.
        extraction_stages = (
            extract_manifest_facts,
            extract_locked_versions,
            extract_source_code,
            extract_import_relationships,
            extract_dependency_technologies,
            extract_entrypoints,
            extract_infrastructure,
            extract_testing,
        )
        for extraction_stage in extraction_stages:
            try:
                extraction_stage(context)
            except (
                ValueError,
                TypeError,
                AttributeError,
                KeyError,
                IndexError,
            ) as error:
                context.add_issue(
                    ".",
                    "extraction_error",
                    f"{extraction_stage.__name__}: {type(error).__name__}; this section may be partial.",
                )
        directories = build_directories(context)
        extract_architecture_signals(context, directories)
        for source_file in context.processed_files():
            try:
                current_hash = hashlib.sha256(
                    (root / source_file.path).read_bytes()
                ).hexdigest()
            except OSError as error:
                raise RepositoryChangedError(
                    f"Source file disappeared during analysis: {source_file.path}"
                ) from error
            if current_hash != source_file.content_hash:
                raise RepositoryChangedError(
                    f"Source file changed during analysis: {source_file.path}"
                )
        if (
            any(issue.category == "source_changed" for issue in context.issues)
            or repository_commit(root) != initial_commit
        ):
            raise RepositoryChangedError(
                "Repository changed during analysis; build a new snapshot."
            )
        snapshot_identity = {
            "extractor_version": "1",
            "python_version": platform.python_version(),
            "options": options.model_dump(exclude={"root_path"}),
            "files": [
                (
                    source_file.path,
                    source_file.status,
                    source_file.content_hash,
                    source_file.size_bytes,
                )
                for source_file in context.files.values()
            ],
            "directories": directory_paths,
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot_identity, sort_keys=True).encode()
        ).hexdigest()
        unique_issues = tuple(
            sorted(
                set(context.issues),
                key=lambda issue: (issue.path, issue.category, issue.message),
            )
        )
        snapshot = RepositorySnapshot(
            repository=RepositoryIdentity(
                name=root.name,
                root_path=str(root),
                commit=initial_commit,
                snapshot_hash=snapshot_hash,
                python_version=platform.python_version(),
            ),
            projects=sorted_unique_records(context.projects),
            files=tuple(context.files.values()),
            directories=directories,
            symbols=sorted_unique_records(context.symbols),
            technologies=sorted_unique_records(context.technologies),
            dependencies=sorted_unique_records(context.dependencies),
            relationships=sorted_unique_records(context.relationships),
            architecture_signals=sorted_unique_records(context.architecture_signals),
            entrypoints=sorted_unique_records(context.entrypoints),
            infrastructure=sorted_unique_records(context.infrastructure),
            testing=sorted_unique_records(context.testing),
            evidence=sorted_unique_records(context.evidence.values()),
            coverage=AnalysisCoverage(
                discovered_files=len(context.files),
                processed_files=len(context.processed_files()),
                retained_bytes=sum(
                    source_file.size_bytes for source_file in context.processed_files()
                ),
                unsupported_source_languages=tuple(
                    sorted(
                        {source_file.language for source_file in context.files.values()}
                        & UNSUPPORTED_SOURCE_LANGUAGES
                    )
                ),
                issues=unique_issues,
                limitations=(
                    "Ignored generated/dependency/VCS directories are not inventoried.",
                    "Architecture signals are static evidence, not architectural compliance judgments.",
                    "Dynamic imports, runtime configuration and unknown import-to-distribution mappings may remain unresolved.",
                    "Test discovery does not measure execution coverage or test correctness.",
                ),
            ),
        )
        validate_snapshot_references(snapshot)
        return snapshot
