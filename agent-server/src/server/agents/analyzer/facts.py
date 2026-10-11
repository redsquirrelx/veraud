"""Turning a Collection into the few facts that decide 'what is this'.

Kept apart from the graph so the graph reads as steps rather than as parsing.
"""

import json
import re
import sys

# Key components reported in a description. The prompt used to ask for "four
# to eight"; eight keeps the listing informative without crowding the prompt.
MAX_KEY_COMPONENTS = 8

# A package __init__.py at least this long is treated as a public API. Chosen
# because build123d's is 289 lines of pure re-exports with zero defs of its own,
# and missing it made the analyzer report a library with no entry point at all.
MIN_PUBLIC_API_LINES = 60

# Standard library names. They are not project dependencies: every Python
# project imports them, so listing them only buries the third-party signal.
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}

# Node.js builtins, plain and `node:`-prefixed. Same idea as STDLIB, for the
# TypeScript side of the graph: `fs` says nothing about what a project is.
NODE_STDLIB = frozenset({
    "assert", "buffer", "child_process", "cluster", "console", "crypto",
    "dgram", "diagnostics_channel", "dns", "events", "fs", "http", "http2",
    "https", "inspector", "module", "net", "os", "path", "perf_hooks",
    "process", "querystring", "readline", "repl", "stream", "string_decoder",
    "timers", "tls", "trace_events", "tty", "url", "util", "v8", "vm",
    "wasi", "worker_threads", "zlib",
})

# Circular groups reported to the model. The graph computes all of them; this
# keeps a pathological repository from crowding out the rest of the facts.
MAX_REPORTED_CYCLES = 5

ENTRYPOINT_NAMES = frozenset({
    "main.py", "__main__.py", "app.py", "wsgi.py", "asgi.py", "manage.py", "cli.py",
})

# What makes a directory an importable package.
PACKAGE_MARKER = "/__init__.py"

# Generated code never carries the project's architecture: it describes the
# tool, not the design. Matched by path only (segments and suffixes), so no
# file content is ever read to decide this.
GENERATED_DIR_MARKERS = frozenset({"generated", "__generated__"})
GENERATED_FILE_INFIX = ".generated."
GENERATED_FILE_SUFFIXES = ("_pb2.py", ".d.ts", ".min.js")

# Cross-cutting plumbing: imported everywhere, deciding nowhere. A logs.py or
# an icons.tsx can top an import-degree ranking while saying nothing about
# how the project is put together, so they are out of the key-components
# ranking. Matched per basename segment (split on -_.), exact and
# case-insensitive, so my_configurator.py and reconfigure.py survive while
# app_logger.py and icon-button.tsx do not. utils/helpers/config are in on
# purpose: shared helpers describe the toolbox, not the architecture.
PLUMBING_STEMS = frozenset({
    "log", "logs", "logger", "logging",
    "icon", "icons",
    "util", "utils", "helper", "helpers",
    "constant", "constants", "config", "configs",
    "theme", "themes", "style", "styles",
})


def _is_generated_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    segments = [segment for segment in lowered.split("/") if segment]
    if any(segment in GENERATED_DIR_MARKERS for segment in segments[:-1]):
        return True
    name = segments[-1] if segments else ""
    if GENERATED_FILE_INFIX in name:
        return True
    return name.endswith(GENERATED_FILE_SUFFIXES)


def _is_plumbing_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    segments = [segment for segment in lowered.split("/") if segment]
    if not segments:
        return False
    name = segments[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    pieces = [piece for piece in re.split(r"[-_.]+", stem) if piece]
    return any(piece in PLUMBING_STEMS for piece in pieces)


def is_rankable(path: str) -> bool:
    """Whether a path may compete for key-component ranking.

    Generated files and cross-cutting plumbing are structurally central and
    architecturally mute, so they sit the ranking out. They stay citable and
    readable everywhere else: this only decides what the architect is asked
    to characterize first.
    """
    return bool(path) and not _is_generated_path(path) and not _is_plumbing_path(path)


def _dump(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_facts(collection: dict, max_chars: int) -> tuple[str, bool]:
    """Condense a collection into the facts that identify a project.

    The full dependency graph is left out on purpose: hundreds of edges do not
    help identify a project and they crowd out the signals that do.

    When the facts run over the budget, detail is dropped but the file listing
    survives. Every later step asks the model to name paths copied verbatim from
    it, so a trimmed listing means the rest of the run has nothing to ask about.
    The paths are therefore the last thing to go.
    """
    repo_map = collection.get("repo_map", {})
    graph = collection.get("dependency_graph", {})
    files = repo_map.get("files", [])

    payload = {
        "root": collection.get("root"),
        "stats": collection.get("stats", {}),
        "package_entrypoints": package_entrypoints(files),
        "entrypoint_candidates": entrypoint_candidates(files),
        "third_party_dependencies": third_party_dependencies(collection),
        "hub_modules": hub_modules(graph.get("edges", []), limit=12),
        "circular_import_groups": cycles(collection),
        # Paths only. The model cites these back verbatim, so anything appended
        # to a path is something it may quote. Size lives in hub_modules, which
        # is where it actually decides anything.
        "files": sorted(item["path"] for item in files if item.get("path")),
    }

    text = _dump(payload)
    if len(text) <= max_chars:
        return text, False

    # Drop what the identification needs least, one at a time. The listing goes
    # last, and only after everything that would have pointed the model at it.
    for droppable in ("hub_modules", "circular_import_groups", "third_party_dependencies"):
        payload.pop(droppable, None)
        text = _dump(payload)
        if len(text) <= max_chars:
            payload["note"] = f"{droppable} omitted to fit the prompt; totals still apply."
            return _dump(payload), True

    return _dump(_minimal(files, max_chars)), True


def _minimal(files: list[dict], budget: int) -> dict:
    """The last resort: paths alone, with nothing else competing for room.

    The warning is shortened too, because it has to survive: a listing the model
    believes is complete when it is not produces invented paths, and that costs
    more than a listing missing a few entries. Entry points are pinned, so there
    is always something to cite even when almost nothing fits.
    """
    for note in (
        "File listing truncated to fit the prompt. This is NOT the whole repository.",
        "Listing truncated. Not the whole repository.",
        "Listing truncated.",
        "",
    ):
        payload = {"note": note, "files": []}
        headroom = budget - len(_dump(payload))

        if headroom <= 0:
            continue

        payload["files"] = _longest_paths(files, headroom)
        return payload

    return {"files": []}


def _longest_paths(files: list[dict], budget: int) -> list[str]:
    """As many paths as fit in the budget, longest first, then re-sorted.

    A long path is a deep file doing something specific, which beats a short one
    that is almost certainly boilerplate. Entry points are pinned so trimming
    never costs the model the one thing it most needs to read.

    Room is measured off the real dump rather than estimated per path, because
    json.dumps' own formatting decides the final size, and guessing it is how a
    prompt ends up over budget.
    """
    pinned = entrypoint_candidates(files)
    rest = sorted(
        (item["path"] for item in files if item.get("path") and item["path"] not in pinned),
        key=len,
        reverse=True,
    )

    kept: list[str] = []

    for path in pinned + rest:
        if _measure([*kept, path]) > budget:
            continue
        kept.append(path)

    return sorted(kept)


def _measure(paths: list[str]) -> int:
    """Characters the paths take inside a trimmed payload."""
    return len(_dump({"note": "", "files": paths}))


def package_entrypoints(files: list[dict]) -> list[str]:
    """Packages that export a public API, which is how a library is entered.

    A published library usually has no main.py at all: consumers import the
    package, so the package directory is the entry point.
    """
    packages = set()

    for item in files:
        path = item.get("path") or ""
        if not path.endswith("__init__.py"):
            continue

        package = path[: -len("/__init__.py")]
        if package and (item.get("symbols") or _lines(item) >= MIN_PUBLIC_API_LINES):
            packages.add(package)

    return sorted(packages)


def entrypoint_candidates(files: list[dict]) -> list[str]:
    """Files whose name says execution starts there."""
    found = set()

    for item in files:
        path = item.get("path") or ""
        name = path.rsplit("/", 1)[-1]

        if name in ENTRYPOINT_NAMES:
            found.add(path)
        elif name == "__init__.py" and _lines(item) >= MIN_PUBLIC_API_LINES:
            # A large package __init__ is a public API even when it only
            # re-exports and defines no functions of its own.
            found.add(path)

    return sorted(found)


def derived_entrypoints(files: list[dict]) -> list[str]:
    """Where execution starts, computed instead of model-chosen.

    Named entry files plus public package APIs, sorted. Deterministic for a
    given listing: the same repository always yields the same entry points,
    which a model asked to pick them cannot promise run to run.
    """
    return sorted(set(entrypoint_candidates(files)) | set(package_entrypoints(files)))


def derived_key_components(
    edges: list[dict], files: list[dict], limit: int = MAX_KEY_COMPONENTS
) -> list[str]:
    """Paths carrying most of the code, computed instead of model-chosen.

    The top hub modules by import degree, excluding generated code and
    cross-cutting plumbing (see is_rankable): where the project's own design
    holds together. Ties break alphabetically so the ranking is stable. When
    the graph has no internal edges at all (languages without import
    extraction), the largest rankable files by lines stand in, same ordering
    rule. Either way the answer is a pure function of the collection,
    identical on every run.
    """
    hubs = hub_modules(edges, limit=limit)
    if hubs:
        return [entry["path"] for entry in hubs]

    ranked = sorted(
        (item for item in files if item.get("path") and is_rankable(item["path"])),
        key=lambda item: (-(item.get("lines") or 0), item["path"]),
    )
    return [item["path"] for item in ranked[:limit]]


def derived_primary_language(files: list[dict]) -> str:
    """Dominant language by lines, alphabetical tie-break.

    Lines, not file count: a hundred tiny config files should not outvote the
    language the project is written in.
    """
    totals: dict[str, int] = {}

    for item in files:
        language = item.get("language") or "unknown"
        totals[language] = totals.get(language, 0) + (item.get("lines") or 0)

    if not totals or sum(totals.values()) <= 0:
        return "unknown"

    best = max(totals.values())
    return min(name for name, total in totals.items() if total == best)


# Directories profiled per description. Enough to see what each area holds
# without reading code; the file listing stays the citable source of paths.
MAX_PROFILED_DIRS = 10
MAX_DIR_SYMBOLS = 6


def directory_profiles(files: list[dict], edges: list[dict]) -> list[dict]:
    """Aggregate what each top-level directory holds, sorted by lines.

    Pure function of the collection: file and line counts, languages present,
    internal import edges in and out, entry files inside, and the top symbol
    names. Deterministic, so the architect reasons over directory content
    instead of directory names.
    """
    grouped: dict[str, dict] = {}

    for item in files:
        path = item.get("path") or ""
        directory = path.split("/", 1)[0] if "/" in path else "(root)"

        entry = grouped.setdefault(directory, {
            "files": 0,
            "lines": 0,
            "languages": {},
            "symbols": [],
            "entrypoints": [],
        })
        entry["files"] += 1
        entry["lines"] += item.get("lines") or 0

        language = item.get("language") or "unknown"
        entry["languages"][language] = entry["languages"].get(language, 0) + 1

        for symbol in item.get("symbols") or []:
            name = symbol.get("name") if isinstance(symbol, dict) else None
            if name:
                entry["symbols"].append(name)

        name = path.rsplit("/", 1)[-1]
        if name in ENTRYPOINT_NAMES or (
            name == "__init__.py" and (item.get("lines") or 0) >= MIN_PUBLIC_API_LINES
        ):
            entry["entrypoints"].append(path)

    degrees: dict[str, dict[str, int]] = {}

    for edge in edges:
        target = edge.get("target")
        if not target:
            continue
        _bump(degrees, _top_dir(edge["source"]), "out")
        _bump(degrees, _top_dir(target), "in")

    profiles = []

    for directory in sorted(grouped, key=lambda name: (-grouped[name]["lines"], name)):
        entry = grouped[directory]
        flow = degrees.get(directory, {})
        profiles.append({
            "directory": directory,
            "files": entry["files"],
            "lines": entry["lines"],
            "languages": dict(sorted(entry["languages"].items())),
            "imports": flow.get("out", 0),
            "imported_by": flow.get("in", 0),
            "entrypoints": sorted(entry["entrypoints"]),
            "symbols": sorted(set(entry["symbols"]))[:MAX_DIR_SYMBOLS],
        })

    return profiles[:MAX_PROFILED_DIRS]


def _top_dir(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "(root)"


def specifier_head(specifier: str) -> str:
    """Top-level name of a dotted import specifier, e.g. `requests` in
    `requests.sessions`. Empty when the specifier names nothing (as `from .
    import x` yields). Shared by third-party listing and external-edge
    mapping so both agree on what a dependency is called.
    """
    return (specifier or "").strip().split(".", 1)[0].strip()


def third_party_dependencies(collection: dict) -> list[str]:
    """Distinct external import names, standard library excluded.

    Every project imports os and json, so they say nothing about what this one
    is. Names are sorted so the same repo always produces the same facts.
    """
    names = set()

    for edge in collection.get("dependency_graph", {}).get("edges", []):
        if edge.get("resolved"):
            continue

        specifier = (edge.get("specifier") or "").strip()
        # `from . import x` yields an empty base and names no dependency.
        if not specifier:
            continue

        head = specifier_head(specifier)
        bare = head.removeprefix("node:")
        if head and head not in STDLIB and bare not in NODE_STDLIB:
            names.add(head)

    return sorted(names)


def cycles(collection: dict) -> list[list[str]]:
    """Circular import groups, already computed by the dependency graph.

    These are facts, not judgements: Tarjan found them. The model is told they
    exist so it can interpret them, not asked to re-derive them.
    """
    found = collection.get("dependency_graph", {}).get("stats", {}).get("cycles", [])

    ordered = sorted(found, key=len, reverse=True)
    return [sorted(group) for group in ordered[:MAX_REPORTED_CYCLES]]


def hub_modules(edges: list[dict], limit: int) -> list[dict]:
    """Files with the most internal edges: where the project holds together.

    Edges touching generated or plumbing paths are dropped first, so a hub
    is a hub of the project's own design rather than of its tooling.
    """
    degrees: dict[str, dict[str, int]] = {}

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if not source or not target:
            continue
        if not is_rankable(source) or not is_rankable(target):
            continue
        _bump(degrees, source, "out")
        _bump(degrees, target, "in")

    ranked = sorted(
        degrees.items(),
        key=lambda item: (-(item[1].get("in", 0) + item[1].get("out", 0)), item[0]),
    )

    return [
        {"path": path, "imported_by": data.get("in", 0), "imports": data.get("out", 0)}
        for path, data in ranked[:limit]
    ]


def known_paths(files: list[dict]) -> set[str]:
    """Every path the model is allowed to name, so nothing invented gets through.

    Files count, and so do package directories: a library's entry point is the
    package, not any file inside it, so `src/build123d` has to validate even
    though no file by that name appears in the listing. A directory only counts
    when it holds an `__init__.py`, which is what makes it a package.
    """
    paths = {item["path"] for item in files if item.get("path")}

    for item in files:
        path = item.get("path") or ""
        if path.endswith(PACKAGE_MARKER):
            directory = path[: -len(PACKAGE_MARKER)].rstrip("/")
            if directory:
                paths.add(directory)

    return paths


# -- helpers ---------------------------------------------------------------


def _bump(degrees: dict[str, dict[str, int]], path: str, direction: str) -> None:
    degrees.setdefault(path, {})[direction] = degrees.setdefault(path, {}).get(direction, 0) + 1


def _lines(item: dict) -> int:
    return item.get("lines") or 0