"""Workspace-bound access to technical files in a retained repository snapshot."""

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from ...services.repository_analysis.schemas import RepositorySnapshot, SourceFile

DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parents[5] / "appdata" / "workspace"
NARRATIVE_DIRECTORIES = frozenset(
    {"docs", "doc", "documentation", "guides", "adr", "adrs"}
)
NARRATIVE_NAMES = (
    "readme",
    "changelog",
    "contributing",
    "license",
    "licence",
    "code_of_conduct",
    "roadmap",
    "authors",
    "notice",
)
TECHNICAL_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".go",
        ".rs",
        ".java",
        ".cs",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".rb",
        ".php",
        ".kt",
        ".swift",
        ".vue",
        ".svelte",
        ".html",
        ".css",
        ".scss",
        ".sass",
        ".sql",
        ".sh",
        ".ps1",
        ".bat",
        ".cmd",
        ".json",
        ".jsonc",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".xml",
        ".graphql",
        ".gql",
        ".proto",
        ".tf",
        ".tfvars",
        ".properties",
        ".lock",
        ".dockerfile",
    }
)
TECHNICAL_NAMES = frozenset(
    {
        "dockerfile",
        "makefile",
        "justfile",
        "procfile",
        "pipfile",
        "pipfile.lock",
        "gemfile",
        "rakefile",
        "cmakelists.txt",
        ".python-version",
        ".node-version",
        ".nvmrc",
        ".editorconfig",
        ".gitignore",
        ".dockerignore",
        ".npmrc",
        ".yarnrc",
        ".prettierrc",
        ".eslintrc",
        ".babelrc",
        ".flake8",
    }
)


class RepositoryAccessError(ValueError):
    """An agent request violated the selected checkout or file access policy."""


def repository_relative_path(path: str, *, allow_root: bool = False) -> str:
    """Reject absolute paths, drives, traversal, streams, and URI-like inputs."""
    if not path or "\0" in path or ":" in path:
        raise RepositoryAccessError("A repository-relative path is required.")
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or PureWindowsPath(path).drive:
        raise RepositoryAccessError("Absolute paths are not permitted.")
    parts = normalized.split("/")
    if ".." in parts:
        raise RepositoryAccessError("Parent traversal is not permitted.")
    normalized = "/".join(part for part in parts if part not in ("", "."))
    if not normalized and not allow_root:
        raise RepositoryAccessError("A file path is required.")
    return normalized or "."


@dataclass(frozen=True)
class RepositoryAccessPolicy:
    workspace_root: Path
    repository_root: Path

    @classmethod
    def bind(
        cls, snapshot: RepositorySnapshot, workspace_root: Path = DEFAULT_WORKSPACE_ROOT
    ):
        workspace = workspace_root.expanduser().resolve()
        repository = Path(snapshot.repository.root_path).expanduser().resolve()
        if repository.parent != workspace:
            raise RepositoryAccessError(
                "Snapshot root must be a single checkout directly inside the configured workspace."
            )
        for source_file in snapshot.files:
            if repository_relative_path(source_file.path) != source_file.path:
                raise RepositoryAccessError(
                    "Snapshot contains a noncanonical file path."
                )
            # Only path metadata is resolved; queries never read live source files.
            if source_file.status == "processed" and not (
                repository / source_file.path
            ).resolve().is_relative_to(repository):
                raise RepositoryAccessError(
                    "Snapshot file path escapes the selected checkout."
                )
        return cls(workspace_root=workspace, repository_root=repository)

    def allows_file(self, source_file: SourceFile) -> bool:
        path = repository_relative_path(source_file.path)
        parts = path.casefold().split("/")
        name = parts[-1]
        if source_file.status != "processed" or source_file.content is None:
            return False
        if any(part in NARRATIVE_DIRECTORIES for part in parts[:-1]):
            return False
        if any(
            name == prefix or name.startswith((prefix + ".", prefix + "-"))
            for prefix in NARRATIVE_NAMES
        ):
            return False
        if name == ".env" or name.startswith(".env."):
            return False
        if Path(name).stem in ("architecture", "design", "security") and Path(
            name
        ).suffix in (".json", ".yaml", ".yml", ".xml"):
            return False
        if name.startswith("requirements") and name.endswith((".txt", ".in")):
            return True
        return (
            name in TECHNICAL_NAMES
            or name.startswith("dockerfile.")
            or Path(name).suffix in TECHNICAL_EXTENSIONS
        )

    def filtered_snapshot(self, snapshot: RepositorySnapshot) -> RepositorySnapshot:
        """Filter before pagination/search, including indirect evidence references."""
        files = tuple(source for source in snapshot.files if self.allows_file(source))
        file_ids = {source.id for source in files}
        paths = {source.path for source in files}
        evidence = tuple(
            record for record in snapshot.evidence if record.file_id in file_ids
        )
        evidence_ids = {record.id for record in evidence}

        def clean(record):
            updates = {}
            if hasattr(record, "evidence_ids"):
                updates["evidence_ids"] = tuple(
                    identifier
                    for identifier in record.evidence_ids
                    if identifier in evidence_ids
                )
            for field_name in ("manifest_paths", "file_paths", "configuration_paths"):
                if hasattr(record, field_name):
                    updates[field_name] = tuple(
                        path for path in getattr(record, field_name) if path in paths
                    )
            return record.model_copy(update=updates)

        def evidenced(records):
            return tuple(
                clean(record)
                for record in records
                if set(record.evidence_ids) & evidence_ids
            )

        symbols = tuple(
            clean(record) for record in snapshot.symbols if record.file_id in file_ids
        )
        symbol_ids = {record.id for record in symbols}
        dependencies = evidenced(snapshot.dependencies)
        infrastructure = evidenced(snapshot.infrastructure)
        entity_ids = (
            file_ids
            | symbol_ids
            | {record.id for record in dependencies + infrastructure}
        )
        relationships = tuple(
            clean(record)
            for record in snapshot.relationships
            if record.source_id in entity_ids
            and (record.target_id is None or record.target_id in entity_ids)
            and set(record.evidence_ids) & evidence_ids
        )
        entrypoints = tuple(
            clean(record)
            for record in snapshot.entrypoints
            if (record.file_id is None or record.file_id in file_ids)
            and (record.symbol_id is None or record.symbol_id in symbol_ids)
            and set(record.evidence_ids) & evidence_ids
        )
        coverage = snapshot.coverage.model_copy(
            update={
                "discovered_files": len(files),
                "processed_files": len(files),
                "retained_bytes": sum(source.size_bytes for source in files),
                "issues": tuple(
                    issue for issue in snapshot.coverage.issues if issue.path in paths
                ),
            }
        )
        return snapshot.model_copy(
            update={
                "files": files,
                "symbols": symbols,
                "evidence": evidence,
                "projects": tuple(clean(record) for record in snapshot.projects),
                "directories": tuple(
                    record
                    for record in snapshot.directories
                    if any(path.startswith(record.path + "/") for path in paths)
                    or record.path == "."
                ),
                "technologies": evidenced(snapshot.technologies),
                "dependencies": dependencies,
                "relationships": relationships,
                "entrypoints": entrypoints,
                "infrastructure": infrastructure,
                "testing": evidenced(snapshot.testing),
                "architecture_signals": (),
                "coverage": coverage,
            }
        )
