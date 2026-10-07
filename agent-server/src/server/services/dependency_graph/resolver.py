import sys
from dataclasses import dataclass
from pathlib import Path

from ...config.logs import get_logger
from .extractors import ImportRecord

logger = get_logger("service.depgraph.resolver")

STDLIB = frozenset(sys.stdlib_module_names)

# Installed distributions give their top-level import names. Checked before
# reporting an unknown dotted name, so `from pydantic import BaseModel` is
# third-party rather than a missing local file.
def _installed_top_levels() -> frozenset[str]:
    try:
        from importlib.metadata import distributions
    except ImportError:
        return frozenset()

    names: set[str] = set()
    try:
        for dist in distributions():
            top = getattr(dist, "name", None)
            if top:
                names.add(str(top).lower().replace("-", "_"))
    except Exception as error:  # noqa: BLE001 - metadata can be half-installed
        logger.debug("could not read installed distributions: %s", error)
        return frozenset()

    return frozenset(names)


THIRD_PARTY = _installed_top_levels()

# A dotted name may sit several segments past the real one, e.g. asking for
# `a.b.c` when only `a` exists locally. Try progressively shorter prefixes.
MAX_SEGMENTS = 12


@dataclass
class Resolution:
    """Where one import record landed."""

    record: ImportRecord
    target: str | None
    resolved: bool
    reason: str | None


class ModuleResolver:
    """Maps a dotted specifier to a repo file.

    Knows the repo layout (flat or src/), which directories are packages, and
    what the standard library looks like. Language independent: it only
    understands dotted names and relative levels, so any extractor can use it.
    """

    def __init__(self, root: Path, files: dict[str, list[str]]) -> None:
        """files maps a repo-relative directory to the Python files it holds."""
        self._root = root
        self._packages = self._index_packages(files)
        self._children = self._index_children(files)
        self._modules = self._index_modules(files)
        self._roots = _import_roots(files)

    def _index_children(self, files: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
        """Package directory -> the module stems directly inside it."""
        children: dict[str, set[str]] = {}

        for directory, names in files.items():
            if not directory or directory not in self._packages:
                continue
            parent = directory.rsplit("/", 1)[0] if "/" in directory else ""

            for name in names:
                if not name.endswith(".py"):
                    continue
                stem = name[:-3]
                if stem != "__init__":
                    children.setdefault(parent, set()).add(stem)

        return {package: tuple(sorted(stems)) for package, stems in children.items()}

    @property
    def packages(self) -> frozenset[str]:
        """Repo-relative directories that can hold importable modules."""
        return self._packages

    # -- indexing -----------------------------------------------------------

    def _index_packages(self, files: dict[str, list[str]]) -> frozenset[str]:
        """Directories that re-export their contents: they hold __init__.py.

        Deliberately not namespace directories. PEP 420 packages are
        importable but expose nothing, so treating them as packages would make
        every sibling import resolve to the namespace itself.
        """
        return frozenset(
            directory
            for directory, names in files.items()
            if directory and "__init__.py" in names
        )

    def _index_modules(self, files: dict[str, list[str]]) -> dict[str, str]:
        """Dotted path relative to the repo root -> file.

        A module can be reached by more than one name: `server` is both the
        `src/` directory and the package inside it. Every alias is registered,
        including the parent packages that hold each module.
        """
        modules: dict[str, str] = {}

        # Packages first: `p/__init__.py` owns the name `p`, and the per-child
        # aliases must never overwrite it.
        ordered = sorted(
            files.items(),
            key=lambda item: ("__init__.py" not in item[1], item[0]),
        )

        for directory, names in ordered:
            dotted_dir = directory.replace("/", ".") if directory else ""

            for name in names:
                if not name.endswith(".py"):
                    continue

                path = f"{directory}/{name}" if directory else name
                stem = name[:-3]

                if stem == "__init__":
                    aliases = [dotted_dir] if dotted_dir else []
                else:
                    module = f"{dotted_dir}.{stem}" if dotted_dir else stem
                    aliases = [module]
                    # A sibling module inside a real package is also reachable
                    # by the package name (`from p import core`), so `p` maps to
                    # every direct child. A namespace package re-exports
                    # nothing, so it gets no such alias.
                    parent = dotted_dir
                    if parent and parent in self._packages:
                        aliases.append(parent)
                        for sibling in self._children.get(parent, ()):
                            aliases.append(f"{parent}.{sibling}")

                for alias in aliases:
                    # Real packages come first, so a package `__init__` must win
                    # over the child aliases registered before it. Otherwise
                    # every sibling resolves to the first child scanned.
                    if alias in modules and alias != module:
                        continue
                    modules[alias] = path

        return modules

    # -- resolution ---------------------------------------------------------

    def resolve(self, record: ImportRecord, source: str) -> Resolution:
        """Resolve one record relative to the file it was written in."""
        if record.kind == "dynamic":
            return Resolution(record, None, False, record.reason or "dynamic")

        if record.level == 0:
            return self._resolve_absolute(record)

        return self._resolve_relative(record, source)

    def _resolve_absolute(self, record: ImportRecord) -> Resolution:
        specifier = record.specifier

        # `src/` is on sys.path, so `from lib2.thing import f` names the module
        # directly. Strip whichever root prefix actually applies.
        for root in self._roots:
            prefixed = f"{root}.{specifier}" if root else specifier
            target = self._lookup(prefixed)
            if target is not None:
                return Resolution(record, target, True, None)

        head = specifier.split(".", 1)[0]

        if head in STDLIB:
            return Resolution(record, None, False, "external")

        target = self._lookup(specifier)
        if target is not None:
            return Resolution(record, target, True, None)

        if head in THIRD_PARTY or head.replace("_", "-") in THIRD_PARTY:
            return Resolution(record, None, False, "external")

        # Unknown head: may be a local path the walk pruned (max_depth,
        # max_files), or a package that is not installed here. Reported rather
        # than dropped, because a silently missing edge becomes a false hole in
        # an architecture diagram.
        return Resolution(record, None, False, "not_found")

    def _resolve_relative(self, record: ImportRecord, source: str) -> Resolution:
        package = _package_of(source)
        anchor = _up(package, record.level - 1)

        if anchor is None:
            return Resolution(record, None, False, "too_many_dots")

        specifier = record.specifier.lstrip(".")
        combined = f"{anchor}.{specifier}" if specifier and anchor else (
            specifier or anchor
        )

        target = self._lookup(combined) if combined else None
        if target is not None:
            return Resolution(record, target, True, None)

        # `from . import mod` names the package, not a module inside it.
        for name in record.names:
            if name == "*":
                continue
            target = self._lookup(f"{combined}.{name}" if combined else name)
            if target is not None:
                return Resolution(record, target, True, None)

        return Resolution(record, None, False, "not_found")

    def _lookup(self, dotted: str) -> str | None:
        """Exact match only.

        Shortening the name would be actively wrong: with `requests.adapters`
        absent locally, falling back to `requests` would claim an edge to some
        unrelated `requests.py`. A name that is not a real module here is not
        local, and the caller reports it as unknown.
        """
        if not dotted or len(dotted.split(".")) > MAX_SEGMENTS:
            return None

        return self._modules.get(dotted)


# -- helpers ---------------------------------------------------------------


def _import_roots(files: dict[str, list[str]]) -> tuple[str, ...]:
    """Dotted prefixes that behave as import roots, longest first.

    Covers the two layouts that matter. A `src/` layout puts `src/` on
    sys.path, so `lib2.thing` names `src/lib2/thing.py`. And any package
    directory is also importable by its own name (`from server.api import ...`),
    which is how a pip-installed project refers to itself. When `root_path`
    points at the package itself rather than the repo, top-level directories
    are the packages and there is no prefix.
    """
    roots: set[str] = set()
    directories = [d for d in files if d]

    if any(d.split("/")[0] == "src" for d in directories):
        roots.add("src")

    # Top-level directories are candidate package names, but only when they
    # look like one: they hold an __init__.py, or nothing else could be.
    tops = {d.split("/")[0] for d in directories}

    for top in tops:
        if f"{top}/__init__.py" in files.get(top, []) or len(tops) == 1:
            roots.add(top)

    return tuple(sorted(roots, key=len, reverse=True))


def _package_of(source: str) -> str:
    """Dotted package that contains this file.

    `a/b/c.py` -> `a.b`. A file at the root has no package.
    """
    trimmed = source.removesuffix(".py")
    directory = trimmed.rsplit("/", 1)[0] if "/" in trimmed else ""
    return directory.replace("/", ".")


def _up(package: str, levels: int) -> str | None:
    """Climb `levels` package levels. None when it climbs past the root."""
    parts = package.split(".") if package else []

    if levels > len(parts):
        return None
    if levels == 0:
        return package

    return ".".join(parts[:len(parts) - levels])