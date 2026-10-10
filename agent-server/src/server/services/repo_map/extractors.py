import ast
from abc import ABC, abstractmethod

from ...config.logs import get_logger
from .schemas import Symbol

logger = get_logger("service.repo-map.extractors")

try:
    import tree_sitter_javascript as _ts_javascript
    import tree_sitter_typescript as _ts_typescript
    from tree_sitter import Language as _TsLanguage
    from tree_sitter import Parser as _TsParser
    from tree_sitter import Query as _TsQuery
    from tree_sitter import QueryCursor as _TsQueryCursor

    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover - missing optional dependency
    logger.warning("tree-sitter grammars missing: typescript/javascript get no symbols")
    _TREE_SITTER_AVAILABLE = False

class SymbolExtractor(ABC):
    """Turns source text into the symbols defined in it.

    One extractor may serve several languages. Implementations must be
    stateless and must never raise on malformed input: return an empty list.
    """

    languages: frozenset[str]

    @abstractmethod
    def extract(self, source: str) -> list[Symbol]:
        """Return the symbols found in source, empty if it does not parse."""
        raise NotImplementedError


class PythonSymbolExtractor(SymbolExtractor):
    """Top-level classes, top-level functions, and their methods.

    Nested functions are deliberately skipped: this is a structural overview,
    not a full symbol table.
    """

    languages = frozenset({"python"})

    @staticmethod
    def _signature_of(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
        try:
            # ast.unparse of an arguments node drops the parentheses, add them back.
            return f"{node.name}({ast.unparse(node.args)})"
        except (AttributeError, TypeError, ValueError):
            # Exotic signatures are not worth failing the whole map over.
            return None

    def extract(self, source: str) -> list[Symbol]:
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            logger.debug("skipping unparseable python: %s", error)
            return []

        symbols: list[Symbol] = []

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                symbols.append(Symbol(name=node.name, kind="class", line=node.lineno))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(Symbol(
                            name=child.name,
                            kind="method",
                            line=child.lineno,
                            signature=self._signature_of(child),
                        ))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(Symbol(
                    name=node.name,
                    kind="function",
                    line=node.lineno,
                    signature=self._signature_of(node),
                ))

        return symbols


def build_default_extractors() -> dict[str, SymbolExtractor]:
    """Map each supported language to the extractor that handles it.

    A language absent from this mapping simply gets no symbols.
    """
    extractors: dict[str, SymbolExtractor] = {}

    for extractor in (PythonSymbolExtractor(), TypeScriptSymbolExtractor()):
        for language in extractor.languages:
            extractors[language] = extractor

    logger.info("Symbol extractors registered for: %s", sorted(extractors))
    return extractors


class TypeScriptSymbolExtractor(SymbolExtractor):
    """Top-level functions, classes, interfaces and their methods.

    Tree-sitter based, so one grammar family covers typescript, tsx,
    javascript and jsx: the extractor tries each grammar and merges what
    parses. Mirrors the Python extractor's scope on purpose: a structural
    overview, not a full symbol table. Never raises: unparseable input or a
    missing grammar yields no symbols.
    """

    languages = frozenset({"typescript", "javascript"})

    _TSX_QUERY = """
    (function_declaration name: (identifier) @function)
    (class_declaration name: (type_identifier) @class)
    (interface_declaration name: (type_identifier) @interface)
    (type_alias_declaration name: (type_identifier) @interface)
    (method_definition name: (property_identifier) @method)
    """

    _JAVASCRIPT_QUERY = """
    (function_declaration name: (identifier) @function)
    (class_declaration name: (identifier) @class)
    (method_definition name: (property_identifier) @method)
    """

    def __init__(self) -> None:
        self._grammars: list[tuple[str, object, str]] = []

        if not _TREE_SITTER_AVAILABLE:
            return

        try:
            self._grammars = [
                ("tsx", _TsLanguage(_ts_typescript.language_tsx()), self._TSX_QUERY),
                ("javascript", _TsLanguage(_ts_javascript.language()), self._JAVASCRIPT_QUERY),
            ]
        except Exception as error:  # noqa: BLE001 - grammar load is version-sensitive
            logger.warning("tree-sitter grammars unusable: %s", error)
            self._grammars = []

    def extract(self, source: str) -> list[Symbol]:
        if not self._grammars:
            return []

        try:
            blob = source.encode("utf-8", errors="ignore")
        except Exception as error:  # noqa: BLE001 - defensive: never raise
            logger.debug("skipping unencodable source: %s", error)
            return []

        found: dict[tuple[str, str, int], Symbol] = {}

        for name, language, patterns in self._grammars:
            try:
                captures = _TsQueryCursor(_TsQuery(language, patterns)).captures(
                    _TsParser(language).parse(blob).root_node
                )
            except Exception as error:  # noqa: BLE001 - grammar/query mismatch
                logger.debug("skipping tree-sitter %s pass: %s", name, error)
                continue

            try:
                pairs = list(captures.items())
            except Exception as error:  # noqa: BLE001 - defensive
                logger.debug("tree-sitter %s query failed: %s", name, error)
                continue

            for kind, nodes in pairs:
                for node in nodes:
                    symbol = self._symbol(kind, node, blob)
                    if symbol is not None:
                        found[(symbol.kind, symbol.name, symbol.line)] = symbol

        return [found[key] for key in sorted(found, key=lambda item: (item[2], item[1]))]

    @staticmethod
    def _symbol(kind: str, node, blob: bytes) -> Symbol | None:
        """A symbol for a captured name, or None when nested or nameless.

        Captures land on the name node, so the checks climb one level to the
        declaration: a top-level declaration hangs off the program (possibly
        through an export), and a method hangs off a top-level class body.
        """
        declaration = node.parent

        if kind == "method":
            # name -> method_definition -> class_body -> class_declaration.
            if declaration is None or declaration.type != "method_definition":
                return None
            body = declaration.parent
            owner = body.parent if body is not None else None
            if (
                body is None
                or body.type != "class_body"
                or owner is None
                or owner.type != "class_declaration"
                or owner.parent is None
                or owner.parent.type not in ("program", "export_statement")
            ):
                return None
        elif (
            declaration is None
            or declaration.parent is None
            or declaration.parent.type not in ("program", "export_statement")
        ):
            return None

        try:
            start = node.start_byte
            end = node.end_byte
            name = blob[start:end].decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - defensive
            return None

        if not name or not name.strip():
            return None

        line = node.start_point[0] + 1
        return Symbol(name=name.strip(), kind=kind, line=line)