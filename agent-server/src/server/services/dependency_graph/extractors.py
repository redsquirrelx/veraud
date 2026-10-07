import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ...config.logs import get_logger

logger = get_logger("service.depgraph.extractors")


@dataclass(frozen=True)
class ImportRecord:
    """One import statement, still unresolved: specifiers are as written."""

    specifier: str
    """Dotted name to resolve, with the leading dots preserved."""

    level: int
    """Leading dots. 0 means absolute."""

    kind: str
    """import | from_import | reexport | type_only | conditional | dynamic"""

    is_from: bool
    """True for `from x import y` style."""

    line: int
    names: tuple[str, ...] = ()
    """Imported names, used to follow `from pkg import submodule`."""

    reason: str | None = None
    """For dynamic imports: why it cannot be resolved statically."""


class ImportExtractor(ABC):
    """Turns source text into unresolved import records.

    One extractor may serve several languages. Implementations must be
    stateless and must not raise on malformed input: return an empty list.
    """

    languages: frozenset[str]

    @abstractmethod
    def extract(self, source: str) -> list[ImportRecord]:
        """Return every import statement found in source."""
        raise NotImplementedError


class _PythonImportVisitor(ast.NodeVisitor):
    """Walks a module tracking the two contexts that change what an import means.

    `if TYPE_CHECKING:` makes an import non-runtime, and `try: ... except
    ImportError` makes it optional. Both change how the edge should be read,
    so both are captured instead of discarded.
    """

    def __init__(self) -> None:
        self.records: list[ImportRecord] = []
        self._type_only = 0
        self._optional = 0

    # -- context tracking ---------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking(node.test):
            self._type_only += 1
            for child in node.body:
                self.visit(child)
            self._type_only -= 1
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        if _catches_import_error(node):
            self._optional += 1
            for child in node.body:
                self.visit(child)
            self._optional -= 1
            for child in node.orelse:
                self.visit(child)
            for handler in node.handlers:
                for child in handler.body:
                    self.visit(child)
            return
        self.generic_visit(node)

    def _kind(self, base: str) -> str:
        if self._type_only:
            return "type_only"
        if self._optional:
            return "conditional"
        return base

    # -- statements ---------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.records.append(ImportRecord(
                specifier=alias.name,
                level=0,
                kind=self._kind("import"),
                is_from=False,
                line=node.lineno,
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = tuple(alias.name for alias in node.names)
        specifier = "." * node.level + (node.module or "")
        kind = self._kind("reexport" if node.level == 0 and any(
            alias.name == "*" for alias in node.names
        ) else "from_import")

        self.records.append(ImportRecord(
            specifier=specifier,
            level=node.level,
            kind=kind,
            is_from=True,
            line=node.lineno,
            names=names,
        ))

        # `from pkg import submodule` also depends on pkg/submodule.
        # Only when the base resolves later; recorded as a candidate here.
        if node.level == 0 and node.module:
            for name in names:
                if name != "*":
                    self.records.append(ImportRecord(
                        specifier=f"{node.module}.{name}",
                        level=0,
                        kind=self._kind("from_import"),
                        is_from=True,
                        line=node.lineno,
                        names=(),
                    ))

    def visit_Call(self, node: ast.Call) -> None:
        name = _called_name(node.func)

        if name in ("__import__", "importlib.import_module", "import_module"):
            argument = node.args[0] if node.args else None
            literal = argument.value if isinstance(argument, ast.Constant) else None

            self.records.append(ImportRecord(
                specifier=literal if isinstance(literal, str) else "<dynamic>",
                level=0,
                kind="dynamic",
                is_from=True,
                line=node.lineno,
                reason=None if isinstance(literal, str) else "dynamic_expr",
            ))
            self.generic_visit(node)
            return

        self.generic_visit(node)


class PythonImportExtractor(ImportExtractor):
    """Static `import` and `from ... import ...` statements.

    Imports inside functions are included: they are still real dependencies,
    just deferred to call time.
    """

    languages = frozenset({"python"})

    def extract(self, source: str) -> list[ImportRecord]:
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            logger.debug("skipping unparseable python: %s", error)
            return []

        visitor = _PythonImportVisitor()
        visitor.visit(tree)

        return _dedupe(visitor.records)


def build_default_extractors() -> dict[str, ImportExtractor]:
    """Map each supported language to the extractor that handles it."""
    extractors: dict[str, ImportExtractor] = {}

    for extractor in (PythonImportExtractor(),):
        for language in extractor.languages:
            extractors[language] = extractor

    logger.info("Import extractors registered for: %s", sorted(extractors))
    return extractors


# -- helpers ---------------------------------------------------------------


def _is_type_checking(test: ast.expr) -> bool:
    """True for `if TYPE_CHECKING:` and `if typing.TYPE_CHECKING:`."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _catches_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        target = handler.type
        if target is None:
            continue
        if isinstance(target, ast.Name) and target.id == "ImportError":
            return True
        if isinstance(target, ast.Tuple) and any(
            isinstance(item, ast.Name) and item.id == "ImportError"
            for item in target.elts
        ):
            return True
    return False


def _called_name(func: ast.expr) -> str | None:
    """Best-effort dotted name of a call target."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        prefix = _called_name(func.value)
        return f"{prefix}.{func.attr}" if prefix else func.attr
    return None


def _dedupe(records: list[ImportRecord]) -> list[ImportRecord]:
    """Drop repeats of the same specifier on the same line.

    `import os, sys` yields one record per name, and the submodule candidates
    from visit_ImportFrom can repeat a specifier already imported directly.
    """
    seen: set[tuple[str, int, str]] = set()
    result: list[ImportRecord] = []

    for record in records:
        key = (record.specifier, record.line, record.kind)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)

    return result