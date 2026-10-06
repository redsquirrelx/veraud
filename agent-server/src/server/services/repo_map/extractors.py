import ast
from abc import ABC, abstractmethod

from ...config.logs import get_logger
from .schemas import Symbol

logger = get_logger("service.repo-map.extractors")

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

    for extractor in (PythonSymbolExtractor(),):
        for language in extractor.languages:
            extractors[language] = extractor

    logger.info("Symbol extractors registered for: %s", sorted(extractors))
    return extractors