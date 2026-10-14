"""Stable, bounded inventory and retained source text; never execute project code."""

import hashlib
import os
from pathlib import Path

from .context import create_identifier
from .schemas import AnalysisIssue, RepositoryAnalysisInput, SourceFile

EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "target",
        "vendor",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".next",
        ".idea",
    }
)
BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".7z",
        ".pyc",
        ".pyd",
        ".dll",
        ".exe",
        ".so",
        ".mp3",
        ".mp4",
        ".wav",
        ".woff",
        ".woff2",
        ".ttf",
        ".db",
        ".sqlite",
        ".bin",
    }
)
SOURCE_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
    ".vue": "vue",
    ".svelte": "svelte",
    ".toml": "toml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".sh": "shell",
    ".ps1": "powershell",
}


def language_for_path(path: str) -> str:
    if Path(path).name.lower().startswith("dockerfile"):
        return "dockerfile"
    return SOURCE_LANGUAGES.get(Path(path).suffix.lower(), "text")


def scan_repository(
    root: Path, options: RepositoryAnalysisInput
) -> tuple[tuple[SourceFile, ...], list[AnalysisIssue], tuple[str, ...]]:
    files: list[SourceFile] = []
    issues: list[AnalysisIssue] = []
    retained_bytes = 0
    processed_count = 0
    directory_paths = {"."}

    def record_walk_error(error: OSError):
        issues.append(
            AnalysisIssue(
                path=str(error.filename or "."),
                category="unreadable_directory",
                message=type(error).__name__,
            )
        )

    for current_directory, directory_names, file_names in os.walk(
        root, onerror=record_walk_error, followlinks=False
    ):
        current_path = Path(current_directory)
        directory_paths.add(current_path.relative_to(root).as_posix())
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in EXCLUDED_DIRECTORIES
            and not (current_path / name).is_symlink()
        )
        depth = len(current_path.relative_to(root).parts)
        if depth >= options.max_depth:
            for directory_name in directory_names:
                relative_path = (
                    (current_path / directory_name).relative_to(root).as_posix()
                )
                issues.append(
                    AnalysisIssue(
                        path=relative_path,
                        category="depth_limit",
                        message="Directory was not traversed.",
                    )
                )
            directory_names[:] = []
        for file_name in sorted(file_names):
            absolute_path = current_path / file_name
            relative_path = absolute_path.relative_to(root).as_posix()
            file_status = "processed"
            content = None
            content_hash = None
            size_bytes = 0
            try:
                file_stat = absolute_path.stat()
                size_bytes = file_stat.st_size
                if (
                    absolute_path.is_symlink()
                    or file_name == ".env"
                    or file_name.startswith(".env.")
                ):
                    file_status = "excluded"
                elif absolute_path.suffix.lower() in BINARY_EXTENSIONS:
                    file_status = "binary"
                elif size_bytes > options.max_file_bytes:
                    file_status = "too_large"
                elif processed_count >= options.max_files:
                    file_status = "file_limit"
                elif retained_bytes + size_bytes > options.max_total_bytes:
                    file_status = "memory_limit"
                else:
                    file_bytes = absolute_path.read_bytes()
                    if b"\0" in file_bytes:
                        file_status = "binary"
                    else:
                        content = file_bytes.decode("utf-8-sig")
                        content_hash = hashlib.sha256(file_bytes).hexdigest()
                        retained_bytes += len(file_bytes)
                        processed_count += 1
                    updated_stat = absolute_path.stat()
                    if (file_stat.st_mtime_ns, file_stat.st_size) != (
                        updated_stat.st_mtime_ns,
                        updated_stat.st_size,
                    ):
                        issues.append(
                            AnalysisIssue(
                                path=relative_path,
                                category="source_changed",
                                message="File changed while being read.",
                            )
                        )
            except UnicodeDecodeError:
                file_status = "invalid_encoding"
            except OSError as error:
                file_status = "unreadable"
                issues.append(
                    AnalysisIssue(
                        path=relative_path,
                        category=file_status,
                        message=type(error).__name__,
                    )
                )
            if file_status in (
                "too_large",
                "file_limit",
                "memory_limit",
                "invalid_encoding",
            ):
                issues.append(
                    AnalysisIssue(
                        path=relative_path,
                        category=file_status,
                        message="Source text was not retained.",
                    )
                )
            detected_language = language_for_path(relative_path)
            if content is not None and content.lstrip().startswith("<?xml"):
                detected_language = "xml"
            files.append(
                SourceFile(
                    id=create_identifier("file", relative_path),
                    path=relative_path,
                    project_id="",
                    language=detected_language,
                    size_bytes=size_bytes,
                    status=file_status,
                    content=content,
                    content_hash=content_hash,
                    line_count=len(content.splitlines())
                    if content is not None
                    else None,
                )
            )
    return (
        tuple(sorted(files, key=lambda source_file: source_file.path)),
        issues,
        tuple(sorted(directory_paths)),
    )
