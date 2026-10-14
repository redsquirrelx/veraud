import ast
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ...config.logs import get_logger

logger = get_logger("service.depgraph.extractors")

try:
    import tree_sitter_javascript as _ts_javascript
    import tree_sitter_typescript as _ts_typescript
    from tree_sitter import Language as _TsLanguage
    from tree_sitter import Parser as _TsParser
    from tree_sitter import Query as _TsQuery
    from tree_sitter import QueryCursor as _TsQueryCursor

    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover - missing optional dependency
    logger.warning("tree-sitter grammars missing: typescript/javascript get no import records")
    _TREE_SITTER_AVAILABLE = False


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
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
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

    for extractor in (PythonImportExtractor(), TypeScriptImportExtractor()):
        for language in extractor.languages:
            extractors[language] = extractor

    logger.info("Import extractors registered for: %s", sorted(extractors))
    return extractors


class TypeScriptImportExtractor(ImportExtractor):
    """Static `import` / `export ... from` plus literal `require()` / `import()`.

    Covers typescript, tsx, javascript and jsx through two grammars: the
    extractor tries each and merges what parses. A call with a non-literal
    argument is dynamic (resolvable at runtime only), mirroring how Python
    treats `__import__` with an expression. Never raises.
    """

    languages = frozenset({"typescript", "javascript"})

    _QUERY = """
    (import_statement) @import_stmt
    (export_statement) @export_stmt
    (call_expression) @call
    """

    def __init__(self) -> None:
        self._grammars: list[tuple[str, object]] = []

        if not _TREE_SITTER_AVAILABLE:
            return

        try:
            self._grammars = [
                ("tsx", _TsLanguage(_ts_typescript.language_tsx())),
                ("javascript", _TsLanguage(_ts_javascript.language())),
            ]
        except Exception as error:  # noqa: BLE001 - grammar load is version-sensitive
            logger.warning("tree-sitter grammars unusable: %s", error)
            self._grammars = []

    def extract(self, source: str) -> list[ImportRecord]:
        if not self._grammars:
            return []

        try:
            blob = source.encode("utf-8", errors="ignore")
        except Exception as error:  # noqa: BLE001 - defensive: never raise
            logger.debug("skipping unencodable source: %s", error)
            return []

        records: list[ImportRecord] = []

        for name, language in self._grammars:
            try:
                tree = _TsParser(language).parse(blob)
                matches = _TsQueryCursor(_TsQuery(language, self._QUERY)).matches(tree.root_node)
                pairs = list(matches)
            except Exception as error:  # noqa: BLE001 - grammar/query mismatch
                logger.debug("skipping tree-sitter %s pass: %s", name, error)
                continue

            for _pattern, captures in pairs:
                for capture, nodes in captures.items():
                    for node in nodes:
                        record = self._record(capture, node, blob)
                        if record is not None:
                            records.append(record)

        return _dedupe(records)

    def _record(self, capture: str, node, blob: bytes) -> ImportRecord | None:
        """One record for a captured statement, or None when it imports nothing."""
        try:
            if capture == "import_stmt":
                return self._import_record(node, blob)
            if capture == "export_stmt":
                return self._export_record(node, blob)
            if capture == "call":
                return self._call_record(node, blob)
        except Exception as error:  # noqa: BLE001 - defensive: never raise
            logger.debug("skipping import node: %s", error)
        return None

    def _import_record(self, node, blob: bytes) -> ImportRecord | None:
        specifier = _statement_source(node, blob)
        if specifier is None:
            return None

        text = blob[node.start_byte:node.end_byte].decode("utf-8", errors="replace").lstrip()
        line = node.start_point[0] + 1

        if text.startswith("import type"):
            return ImportRecord(specifier, 0, "type_only", True, line)

        if _has_child(node, "import_clause"):
            return ImportRecord(specifier, 0, "from_import", True, line)

        # Bare `import "./setup"`: a side effect, no names.
        return ImportRecord(specifier, 0, "import", False, line)

    def _export_record(self, node, blob: bytes) -> ImportRecord | None:
        # `export { x }` without a source exports nothing from elsewhere.
        specifier = _statement_source(node, blob)
        if specifier is None:
            return None

        return ImportRecord(specifier, 0, "reexport", True, node.start_point[0] + 1)

    def _call_record(self, node, blob: bytes) -> ImportRecord | None:
        function = node.child_by_field_name("function")
        if function is None:
            return None

        name = (
            blob[function.start_byte:function.end_byte].decode("utf-8", errors="replace")
            if function.type == "identifier"
            else "import"
            if function.type == "import"
            else None
        )
        if name not in ("require", "import"):
            return None

        line = node.start_point[0] + 1
        arguments = node.child_by_field_name("arguments")
        named = arguments.named_children if arguments is not None else []
        first = named[0] if named else None

        if first is not None and first.type == "string" and _is_plain_string(first):
            specifier = _string_text(first, blob)
            if specifier:
                return ImportRecord(specifier, 0, "import", False, line)

        return ImportRecord("<dynamic>", 0, "dynamic", False, line, reason="dynamic_expr")


def _statement_source(node, blob: bytes) -> str | None:
    """The `source` module string of an import/export statement.

    Only the statement's own source field counts: string literals inside the
    body (defaults, comparisons) are not modules.
    """
    source = node.child_by_field_name("source")
    if source is None or source.type != "string":
        return None

    text = _string_text(source, blob)
    return text or None


def _string_text(node, blob: bytes) -> str | None:
    """Raw text of a string node without its quotes."""
    for child in node.children:
        if child.type == "string_fragment":
            return blob[child.start_byte:child.end_byte].decode("utf-8", errors="replace")

    text = blob[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text or None


def _is_plain_string(node) -> bool:
    """A string literal, not a template with substitutions."""
    return not any(child.type == "template_substitution" for child in node.children)


def _has_child(node, kind: str) -> bool:
    return any(child.type == kind for child in node.children)


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