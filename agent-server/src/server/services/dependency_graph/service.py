import os
from collections import Counter
from pathlib import Path

from ...config.logs import get_logger
from ..base import BaseRepresentationService
from .extractors import ImportExtractor, ImportRecord, build_default_extractors
from .resolver import ModuleResolver
from .schemas import (
    DependencyGraphInput,
    DependencyGraphOutput,
    DependencyGraphStats,
    ImportEdge,
)

logger = get_logger("service.depgraph")


IGNORED_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", "dist", "build", "target", "vendor",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
})

ALLOWED_DOT_DIRS = frozenset({".github", ".gitlab", ".circleci"})

IGNORED_SUFFIXES = frozenset({".pyc", ".pyo", ".pyd", ".so"})


def _keep_dir(name: str) -> bool:
    if name in IGNORED_DIRS:
        return False
    return not name.startswith(".") or name in ALLOWED_DOT_DIRS


def _is_submodule_probe(record: ImportRecord) -> bool:
    """True for the synthetic `pkg.name` records the extractor adds.

    `from pkg import name` produces two records: the real one for `pkg`, plus a
    probe for `pkg.name` used to tell a submodule from a plain attribute. The
    probe carries no imported names, which is what distinguishes it.
    """
    return record.level == 0 and not record.names and "." in record.specifier


class DependencyGraphService(BaseRepresentationService[DependencyGraphInput, DependencyGraphOutput]):
    """Which repo file depends on which, resolved to real files.

    Two layers: an extractor turns source text into unresolved records, and a
    shared resolver maps each dotted specifier to a file. Adding a language
    means adding an extractor, never touching the resolver.
    """

    representation_type = "dependency_graph"
    output_schema = DependencyGraphOutput

    def __init__(self, extractors: dict[str, ImportExtractor] | None = None) -> None:
        self._extractors = extractors or build_default_extractors()

    async def create(self, input_data: DependencyGraphInput) -> DependencyGraphOutput:
        root = Path(input_data.root_path).expanduser().resolve()

        if not root.is_dir():
            raise FileNotFoundError(f"DependencyGraph root is not a directory: {root}")

        logger.info(
            "DependencyGraph mapping root=%s max_depth=%d max_files=%d",
            root, input_data.max_depth, input_data.max_files,
        )

        grouped, truncated = _collect_python_files(root, input_data.max_depth, input_data.max_files)
        resolver = ModuleResolver(root, grouped)

        sources = [
            f"{directory}/{name}" if directory else name
            for directory, names in grouped.items()
            for name in names
        ]

        edges: list[ImportEdge] = []
        external: Counter[str] = Counter()
        unresolved: list[str] = []
        dynamic = 0

        extractor = self._extractors.get("python")

        for relative in sources:
            if extractor is None:
                break

            text = _read_text(root / relative)
            if text is None:
                continue

            for record in extractor.extract(text):
                resolution = resolver.resolve(record, relative)

                if resolution.target is not None:
                    # A file importing itself means the specifier matched the
                    # package `__init__.py` that holds it, not a real cycle.
                    if resolution.target == relative:
                        # A file importing itself means the specifier matched the
                        # package `__init__.py` that holds it, not a real cycle.
                        continue

                    edge = ImportEdge(
                        source=relative,
                        target=resolution.target,
                        specifier=record.specifier,
                        kind=record.kind,
                        resolved=True,
                        level=record.level,
                        line=record.line,
                    )
                    if edge not in edges:
                        edges.append(edge)
                    continue

                is_probe = _is_submodule_probe(record)

                if record.kind == "dynamic":
                    dynamic += 1
                elif resolution.reason == "not_found" and record.level == 0:
                    # `from pkg import name` also emits a `pkg.name` probe to
                    # detect submodules. When `pkg.name` is not a module it is
                    # just an attribute of pkg, already covered by the base
                    # record, so it is noise rather than a missing edge.
                    if not is_probe:
                        unresolved.append(f"{relative}|{record.specifier}")
                elif not is_probe:
                    # Count only the base specifier: the probes would add
                    # `abc.ABC` next to `abc`, and both mean one dependency.
                    external[record.specifier] += 1

                if (input_data.include_external and not is_probe) or record.kind == "dynamic":
                    edges.append(ImportEdge(
                        source=relative,
                        target=None,
                        specifier=record.specifier,
                        kind=record.kind,
                        resolved=False,
                        reason=resolution.reason or "external",
                        level=record.level,
                        line=record.line,
                    ))
                elif resolution.reason == "not_found":
                    # A dotted name that is neither local nor stdlib is
                    # ambiguous: third-party (`requests.adapters`) or a file the
                    # walk pruned. Kept out of the graph but reported, so the
                    # consumer can tell a missing edge from a missing file.
                    logger.debug(
                        "DependencyGraph unresolved %s:%d specifier=%r",
                        relative, record.line, record.specifier,
                    )

        internal = sum(1 for edge in edges if edge.resolved)
        cycles = _find_cycles(edges) if input_data.detect_cycles else []

        stats = DependencyGraphStats(
            files=len(sources),
            edges=len(edges),
            internal=internal,
            external=len(external),
            unresolved=unresolved,
            dynamic=dynamic,
            truncated=truncated,
            cycles=cycles,
        )

        logger.info(
            "DependencyGraph done files=%d edges=%d internal=%d external=%d "
            "unresolved=%d dynamic=%d cycles=%d",
            stats.files, stats.edges, stats.internal, stats.external,
            len(stats.unresolved), stats.dynamic, len(cycles),
        )

        return DependencyGraphOutput(
            root=str(root),
            edges=edges,
            stats=stats,
        )


# -- file walking ----------------------------------------------------------


def _collect_python_files(root: Path, max_depth: int, max_files: int) -> tuple[dict[str, list[str]], bool]:
    """Python files grouped by repo-relative directory, in stable order.

    Grouping by directory is what lets the resolver tell a package from a
    plain folder, so it is the shape the resolver consumes.
    """
    grouped: dict[str, list[str]] = {}
    total = 0
    truncated = False

    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)

        if len(current_path.relative_to(root).parts) >= max_depth:
            dirnames[:] = []

        dirnames[:] = sorted(name for name in dirnames if _keep_dir(name))

        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            if Path(filename).suffix.lower() in IGNORED_SUFFIXES:
                continue

            directory = current_path.relative_to(root).as_posix()
            if directory == ".":
                directory = ""

            grouped.setdefault(directory, []).append(filename)
            total += 1

            if total > max_files:
                truncated = True
                break

        if truncated:
            break

    return grouped, truncated


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        logger.warning("DependencyGraph could not read %s: %s", path, error)
        return None


# -- cycles ----------------------------------------------------------------


def _find_cycles(edges: list[ImportEdge]) -> list[list[str]]:
    """Strongly connected components with more than one member, plus self-loops.

    Sorted so the output is stable between runs.
    """
    graph: dict[str, set[str]] = {}

    for edge in edges:
        if edge.target is None:
            continue
        graph.setdefault(edge.source, set()).add(edge.target)
        graph.setdefault(edge.target, set())

    index_counter = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index_counter
        indices[node] = index_counter
        lowlink[node] = index_counter
        index_counter += 1
        stack.append(node)
        on_stack.add(node)

        for neighbour in sorted(graph.get(node, ())):
            if neighbour not in indices:
                strongconnect(neighbour)
                lowlink[node] = min(lowlink[node], lowlink[neighbour])
            elif neighbour in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbour])

        if lowlink[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            strongconnect(node)

    return sorted(components)


def _self_loops(edges: list[ImportEdge]) -> list[list[str]]:
    return sorted([
        [edge.source] for edge in edges
        if edge.target is not None and edge.target == edge.source
    ])