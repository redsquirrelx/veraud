import os
from pathlib import Path

from ...config.logs import get_logger
from ..base import BaseRepresentationService
from .extractors import SymbolExtractor, build_default_extractors
from .schemas import RepoFile, RepoMapInput, RepoMapOutput, RepoMapStats, Symbol

logger = get_logger("service.repo-map")


IGNORED_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", "dist", "build", "target", "vendor",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
})

# Hidden paths that say something about code quality, so they stay in the map.
# Everything else hidden is dropped: caches, VCS internals, .env and secrets.
ALLOWED_DOT_DIRS = frozenset({
    ".github", ".gitlab", ".circleci",
})

ALLOWED_DOT_FILES = frozenset({
    ".editorconfig", ".flake8", ".pylintrc", ".mypy.ini", ".prettierrc",
})

IGNORED_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".pdf",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".whl", ".jar",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".ttf", ".woff", ".woff2",
    ".bin", ".db", ".sqlite", ".lock", ".map",
})

LANGUAGES: dict[str, str] = {
    ".py": "python", ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".html": "html", ".css": "css", ".scss": "css",
    ".sql": "sql", ".sh": "shell", ".ps1": "powershell",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".rs": "rust", ".go": "go",
}

DEFAULT_LANGUAGE = "text"

# Files larger than this are not read into memory just to count lines: their
# line count is streamed instead. Everything smaller is read as text.
MAX_BYTES_TO_READ = 512 * 1024


class _DirNode:
    """Builds the directory hierarchy while the walk flattens it."""

    def __init__(self) -> None:
        self.dirs: dict[str, _DirNode] = {}
        self.files: list[RepoFile] = []


def _language_of(path: Path) -> str:
    return LANGUAGES.get(path.suffix.lower(), DEFAULT_LANGUAGE)


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as error:
        logger.warning("RepoMap could not stat %s: %s", path, error)
        return 0


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        logger.warning("RepoMap could not read %s: %s", path, error)
        return None


def _count_lines(path: Path) -> int:
    """Count newlines in a large file without loading it into memory.

    Binary content is harmless here: a stray byte that decodes to U+000A
    would only shift the count by one on a file we were not going to read.
    """
    total = 0
    seen = False
    last = b"\n"

    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                seen = True
                total += chunk.count(b"\n")
                last = chunk[-1:]
    except OSError as error:
        logger.warning("RepoMap could not count lines in %s: %s", path, error)
        return 0

    if not seen:
        return 0

    # A file not ending in a newline still has a last, partial line.
    return total if last == b"\n" else total + 1


def _keep_dir(name: str) -> bool:
    if name in IGNORED_DIRS:
        return False
    return not name.startswith(".") or name in ALLOWED_DOT_DIRS


def _keep_file(name: str) -> bool:
    if name in IGNORED_SUFFIXES:
        return False
    if Path(name).suffix.lower() in IGNORED_SUFFIXES:
        return False
    return not name.startswith(".") or name in ALLOWED_DOT_FILES


def _collect_files(root: Path, max_depth: int) -> list[Path]:
    """Walk the tree in a stable order, pruning noise and too-deep levels."""
    collected: list[Path] = []

    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)

        if len(current_path.relative_to(root).parts) >= max_depth:
            dirnames[:] = []

        dirnames[:] = sorted(name for name in dirnames if _keep_dir(name))

        for filename in sorted(filenames):
            if _keep_file(filename):
                collected.append(current_path / filename)

    return collected


def _insert(root: _DirNode, relative_path: str, repo_file: RepoFile) -> None:
    node = root
    parts = relative_path.split("/")
    for part in parts[:-1]:
        node = node.dirs.setdefault(part, _DirNode())
    node.files.append(repo_file)


def _symbol_label(symbol: Symbol) -> str:
    if symbol.kind == "class":
        return f"class {symbol.name}"
    if symbol.signature is not None:
        return f"def {symbol.signature}"
    return f"def {symbol.name}()"


def _file_label(name: str, repo_file: RepoFile) -> str:
    parts = [name]
    if repo_file.lines is not None:
        parts.append(f"{repo_file.lines} L")
    if repo_file.symbols:
        parts.append(f"{len(repo_file.symbols)} sym")
    return "  ".join(parts)


def _entries(node: _DirNode) -> list[tuple[bool, str, RepoFile | None]]:
    items: list[tuple[bool, str, RepoFile | None]] = [
        (True, name, None) for name in node.dirs
    ]
    items += [(False, repo_file.path.rsplit("/", 1)[-1], repo_file) for repo_file in node.files]
    return sorted(items, key=lambda item: (not item[0], item[1]))


def _render(node: _DirNode, prefix: str = "") -> list[str]:
    lines: list[str] = []
    items = _entries(node)

    for index, (is_dir, name, repo_file) in enumerate(items):
        is_last = index == len(items) - 1
        branch = "`-- " if is_last else "|-- "
        child_prefix = prefix + ("    " if is_last else "|   ")

        if is_dir:
            lines.append(f"{prefix}{branch}{name}/")
            lines.extend(_render(node.dirs[name], child_prefix))
            continue

        assert repo_file is not None
        lines.append(f"{prefix}{branch}{_file_label(name, repo_file)}")

        if repo_file.symbols:
            for symbol in repo_file.symbols:
                lines.append(
                    f"{child_prefix}    {symbol.line:>5}  {_symbol_label(symbol)}"
                )

    return lines


class RepoMapService(BaseRepresentationService[RepoMapInput, RepoMapOutput]):
    """Structural map of a repository: a directory tree plus, for every
    language an extractor handles, the symbols defined in each file.

    Pure filesystem work, no model involved, so it is fast and deterministic.
    """

    representation_type = "repo_map"
    output_schema = RepoMapOutput

    def __init__(self, extractors: dict[str, SymbolExtractor] | None = None) -> None:
        self._extractors = extractors or build_default_extractors()

    async def create(self, input_data: RepoMapInput) -> RepoMapOutput:
        root = Path(input_data.root_path).expanduser().resolve()

        if not root.is_dir():
            raise FileNotFoundError(f"RepoMap root is not a directory: {root}")

        logger.info(
            "RepoMap mapping root=%s max_depth=%d max_files=%d symbols=%s",
            root, input_data.max_depth, input_data.max_files,
            input_data.include_symbols,
        )

        paths = _collect_files(root, input_data.max_depth)
        included = paths[: input_data.max_files]

        tree_root = _DirNode()
        files: list[RepoFile] = []
        total_lines = 0

        for path in included:
            language = _language_of(path)
            size = _size_of(path)
            extractor = self._extractors.get(language)
            has_extractor = extractor is not None
            is_small = size <= MAX_BYTES_TO_READ

            text = _read_text(path) if (has_extractor or is_small) else None

            if text is not None:
                lines = len(text.splitlines())
            elif not is_small:
                # Too big to hold, but the line count still belongs in the stats.
                lines = _count_lines(path)
            else:
                lines = None

            if lines is not None:
                total_lines += lines

            symbols: list[Symbol] = []
            if input_data.include_symbols and extractor is not None and text is not None:
                symbols = extractor.extract(text)

            repo_file = RepoFile(
                path=path.relative_to(root).as_posix(),
                language=language,
                size_bytes=size,
                lines=lines,
                symbols=symbols,
            )

            files.append(repo_file)
            _insert(tree_root, repo_file.path, repo_file)

        rendered = [f"{root.name or root}/", *_render(tree_root)]

        stats = RepoMapStats(
            total_files=len(paths),
            included_files=len(files),
            truncated=len(paths) > len(files),
            total_lines=total_lines,
        )

        logger.info(
            "RepoMap done files=%d/%d lines=%d truncated=%s",
            stats.included_files, stats.total_files, total_lines, stats.truncated,
        )

        return RepoMapOutput(
            root=str(root),
            tree="\n".join(rendered),
            files=files,
            stats=stats,
        )