
"""Detección y evaluación estática de capacidades funcionales.

Este módulo reutiliza los hechos producidos por RepositoryAnalysisService.
No ejecuta el sistema analizado ni mide cobertura de pruebas.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .schemas import (
    CapabilityCall,
    CapabilityFinding,
    CodeFragment,
    DocumentReference,
    EvidenceLocation,
    FindingClassification,
    FunctionalAdequacyInput,
    FunctionalCapability,
    SubattributeName,
    SubattributeSummary,
)

MAX_SYMBOL_CAPABILITIES = 60
MAX_SNIPPET_LINES = 40
MAX_RELATIONSHIPS = 5
MAX_DOCUMENT_REFERENCES = 500

DOCUMENT_LANGUAGE = "markdown"
REQUIREMENT_ID_RE = re.compile(r"\bREQ-\d+\b")
MARKDOWN_HEADING_RE = re.compile(
    r"^(?P<level>#{1,6})\s+(?P<text>\S.*?)\s*$"
)
HTTP_METHOD_RE = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\b")
ROUTE_PATH_RE = re.compile(r"/(?:[\w{}._-]+/)*[\w{}._-]+")
REFERENCE_KIND_ORDER = {"definition": 0, "mapping": 1, "mention": 2}

ENTRYPOINT_KINDS = frozenset(
    {
        "application",
        "cli",
        "http_endpoint",
        "framework_page",
        "public_api",
        "service",
    }
)
TEST_PATH_MARKERS = (
    "/tests/",
    "/test/",
    "tests/",
    "test_",
    "_test.",
    ".spec.",
    ".test.",
)

FRAGMENT_PATH_RE = re.compile(r"^(.*):(\d+)-(\d+)$")
PYTHON_DECORATOR_RE = re.compile(
    r"^\s*@(?:[A-Za-z_]\w*\.)*"
    r"(get|post|put|patch|delete|head|options|route|api_route)"
    r"\(\s*(['\"])(.*?)\2",
    re.MULTILINE,
)
PYTHON_DEF_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)
PYTHON_CLASS_RE = re.compile(
    r"^\s*class\s+([A-Za-z_]\w*)\s*[:(]",
    re.MULTILINE,
)
PYTHON_MAIN_RE = re.compile(
    r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:",
    re.MULTILINE,
)

PYTHON_PASS_RE = re.compile(r"^pass(?:\s*#.*)?$")
PYTHON_ELLIPSIS_STATEMENT_RE = re.compile(r"^\.\.\.(?:\s*#.*)?$")
PYTHON_NOT_IMPLEMENTED_RE = re.compile(
    r"^raise\s+NotImplementedError\b"
)
PYTHON_DOCSTRING_START_RE = re.compile(
    r"^[rRuUbB]{0,2}('''|\"\"\")"
)
PYTHON_INLINE_DEF_RE = re.compile(
    r"^(?:async\s+)?def\s+[A-Za-z_]\w*\s*\("
)
JS_INLINE_FUNCTION_RE = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+"
    r"[A-Za-z_$][\w$]*\s*\("
)
JS_THROW_RE = re.compile(
    r"^throw\s+new\s+[A-Za-z_$][\w$]*\s*\(\s*"
    r"(?P<quote>['\"`])(?P<message>.*?)(?P=quote)\s*\)"
    r"\s*;?\s*(?://.*)?$"
)
NOT_IMPLEMENTED_MESSAGE_RE = re.compile(
    r"\b(?:not[\s_-]*(?:yet[\s_-]+)?implemented|unimplemented)\b",
    re.IGNORECASE,
)

CLASSIFICATION_CRITERIA = {
    "confirmado": (
        "Existe evidencia observada, rastreable y no ambigua de la "
        "característica evaluada. No implica cumplimiento de requisitos "
        "reales ni corrección funcional frente a especificaciones ausentes."
    ),
    "probable": (
        "Existe evidencia parcial, inferida o incompleta que sugiere la "
        "característica evaluada, pero no permite demostrarla plenamente."
    ),
    "no_verificado": (
        "No hay evidencia suficiente, el código no fue retenido o la "
        "conclusión depende de especificaciones o ejecuciones no disponibles."
    ),
}

ATTRIBUTE_CRITERIA = {
    "completitud": {
        "confirmado": (
            "La capacidad tiene evidencia observada y una implementación "
            "estática no vacía."
        ),
        "probable": (
            "La capacidad está declarada o inferida, pero su implementación "
            "es parcial, es un esqueleto o no puede resolverse por completo."
        ),
        "no_verificado": (
            "No se dispone de código retenido suficiente para comprobar la "
            "existencia de la capacidad."
        ),
    },
    "correccion": {
        "confirmado": (
            "La implementación estática no presenta marcadores de esqueleto "
            "ni contradicciones evidentes; esto no demuestra corrección "
            "funcional sin especificaciones."
        ),
        "probable": (
            "La implementación existe, pero su resolución estática es parcial "
            "o depende de comportamiento no visible."
        ),
        "no_verificado": (
            "No hay código suficiente o la implementación es un esqueleto, "
            "por lo que no puede evaluarse su corrección."
        ),
    },
    "pertinencia": {
        "confirmado": (
            "La capacidad es un punto de entrada observado o participa en "
            "relaciones internas del repositorio."
        ),
        "probable": (
            "La capacidad es un símbolo público o un punto de entrada "
            "inferido, pero no se demostró su uso dentro del repositorio."
        ),
        "no_verificado": (
            "La capacidad carece de evidencia o de relaciones que permitan "
            "vincularla con el comportamiento del sistema."
        ),
    },
}

BASE_EXPLORATORY_LIMITATIONS = (
    (
        "No se proporcionaron requisitos funcionales; la auditoría es "
        "exploratoria y no demuestra el cumplimiento de especificaciones "
        "reales."
    ),
    (
        "Las capacidades se infieren estáticamente a partir de puntos de "
        "entrada, símbolos y relaciones; el sistema analizado no fue ejecutado."
    ),
    (
        "La corrección se evalúa solo con indicadores estáticos; no se "
        "ejecutaron pruebas ni se calculó cobertura funcional."
    ),
    (
        "La propagación no detecta errores lógicos de implementación; un "
        "método puede estar implementado y aun así ser funcionalmente "
        "incorrecto. Esa detección requiere una capacidad de análisis "
        "distinta."
    ),
    (
        "La propagación entre capacidades usa solo llamadas resueltas "
        "estáticamente en Python; las importaciones, llamadas dinámicas, "
        "relaciones ambiguas y el código JavaScript/TypeScript no se "
        "propagan."
    ),
)


def _fragment_index(
    fragments: Iterable[CodeFragment],
) -> dict[str, list[tuple[int, int, CodeFragment]]]:
    index: dict[str, list[tuple[int, int, CodeFragment]]] = {}

    for fragment in fragments:
        match = FRAGMENT_PATH_RE.match(fragment.file_path)
        if match is None:
            continue
        path = match.group(1)
        start_line = int(match.group(2))
        end_line = int(match.group(3))
        index.setdefault(path, []).append(
            (start_line, end_line, fragment)
        )

    return index


def _matching_fragment(
    index: dict[str, list[tuple[int, int, CodeFragment]]],
    path: str,
    start_line: int | None,
    end_line: int | None,
) -> CodeFragment | None:
    if start_line is None:
        return None

    end_line = end_line or start_line

    for fragment_start, fragment_end, fragment in index.get(path, []):
        if fragment_start <= start_line <= fragment_end:
            return fragment
        if start_line <= fragment_start <= end_line:
            return fragment

    return None


def _source_snippet(
    content: str | None,
    start_line: int | None,
    end_line: int | None,
) -> str | None:
    if content is None or start_line is None:
        return None

    lines = content.splitlines()
    end_line = end_line or start_line
    if start_line < 1 or end_line < start_line:
        return None

    selected = lines[start_line - 1 : min(end_line, start_line - 1 + MAX_SNIPPET_LINES)]
    if not selected:
        return None

    return "\n".join(selected)


def _evidence_location(
    evidence: Any,
    files_by_id: dict[str, Any],
    symbols_by_id: dict[str, Any],
    fragments_by_path: dict[str, list[tuple[int, int, CodeFragment]]],
    symbol_id: str | None = None,
) -> EvidenceLocation:
    source_file = files_by_id.get(evidence.file_id)
    path = evidence.path
    content = source_file.content if source_file is not None else None
    symbol = symbols_by_id.get(symbol_id) if symbol_id else None
    fragment = _matching_fragment(
        fragments_by_path,
        path,
        evidence.start_line,
        evidence.end_line,
    )

    return EvidenceLocation(
        file_path=path,
        start_line=evidence.start_line,
        end_line=evidence.end_line,
        symbol=symbol.qualified_name if symbol is not None else None,
        fragment_id=fragment.fragment_id if fragment is not None else None,
        snippet=_source_snippet(
            content,
            evidence.start_line,
            evidence.end_line,
        ),
    )


def _relationship_labels(
    relationships: Iterable[Any],
    source_file_id: str,
    files_by_id: dict[str, Any],
) -> list[str]:
    labels = []

    for relationship in relationships:
        if (
            relationship.source_id != source_file_id
            or relationship.resolution != "internal"
            or relationship.kind == "contains"
        ):
            continue
        labels.append(f"importa: {relationship.specifier}")
        if len(labels) >= MAX_RELATIONSHIPS:
            break

    return labels


def _is_test_path(path: str) -> bool:
    normalized = f"/{path.strip('/')}/"
    return any(marker in normalized for marker in TEST_PATH_MARKERS)


@dataclass(frozen=True)
class _NameBinding:
    line: int
    kind: str
    target_symbol: Any | None = None


@dataclass
class _PythonScope:
    local_names: set[str] = field(default_factory=set)
    bindings: dict[str, list[_NameBinding]] = field(default_factory=dict)
    global_names: set[str] = field(default_factory=set)
    nonlocal_names: set[str] = field(default_factory=set)
    parent: _PythonScope | None = None


def _python_import_targets(
    source_file_id: str,
    relationships: Iterable[Any],
) -> dict[str, str]:
    targets: dict[str, str] = {}
    for relationship in relationships:
        if (
            relationship.source_id != source_file_id
            or relationship.target_id is None
            or relationship.resolution != "internal"
            or relationship.kind not in ("import", "from_import", "reexport")
        ):
            continue
        targets.setdefault(relationship.specifier, relationship.target_id)
    return targets


def _imported_function_symbol(
    target_file_id: str | None,
    imported_name: str,
    functions_by_file: dict[tuple[str, str], list[Any]],
) -> Any | None:
    if target_file_id is None:
        return None

    candidates = [
        symbol
        for symbol in functions_by_file.get(
            (target_file_id, imported_name), ()
        )
        if symbol.parent_symbol_id is None
    ]
    return candidates[0] if len(candidates) == 1 else None


def _bound_target_names(target: ast.AST):
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _bound_target_names(element)
    elif isinstance(target, ast.Starred):
        yield from _bound_target_names(target.value)


class _ScopeBindingCollector(ast.NodeVisitor):
    """Recolecta enlaces directos sin entrar en funciones ni clases anidadas."""

    def __init__(
        self,
        *,
        file_symbols: list[Any],
        import_targets: dict[str, str],
        functions_by_file: dict[tuple[str, str], list[Any]],
    ) -> None:
        self.file_symbols = file_symbols
        self.import_targets = import_targets
        self.functions_by_file = functions_by_file
        self.scope = _PythonScope()

    def _bind(
        self,
        name: str,
        line: int,
        kind: str,
        target_symbol: Any | None = None,
    ) -> None:
        self.scope.local_names.add(name)
        self.scope.bindings.setdefault(name, []).append(
            _NameBinding(line, kind, target_symbol)
        )

    def bind_parameter(self, name: str, line: int) -> None:
        self._bind(name, line, "shadow")

    def _bind_target(self, target: ast.AST, line: int) -> None:
        for name in _bound_target_names(target):
            self._bind(name, line, "shadow")

    def _bind_definition(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    ) -> None:
        target_symbol = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            target_symbol = _function_symbol(node, self.file_symbols)
        self._bind(node.name, node.lineno, "definition", target_symbol)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._bind_definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._bind_definition(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._bind_definition(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            local_name = imported.asname or imported.name.split(".", 1)[0]
            self._bind(local_name, node.lineno, "import")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        specifier = "." * node.level + (node.module or "")
        target_file_id = self.import_targets.get(specifier)
        for imported in node.names:
            if imported.name == "*":
                continue
            local_name = imported.asname or imported.name
            target_symbol = _imported_function_symbol(
                target_file_id,
                imported.name,
                self.functions_by_file,
            )
            self._bind(
                local_name,
                node.lineno,
                "import",
                target_symbol,
            )

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._bind_target(target, node.lineno)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._bind_target(node.target, node.lineno)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._bind_target(node.target, node.lineno)
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._bind_target(node.target, node.lineno)
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self._bind_target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._bind_target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars, node.lineno)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars, node.lineno)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._bind(node.name, node.lineno, "shadow")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.scope.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.scope.nonlocal_names.update(node.names)


def _build_python_scope(
    body: list[ast.stmt],
    *,
    owner: ast.FunctionDef | ast.AsyncFunctionDef | None,
    file_symbols: list[Any],
    import_targets: dict[str, str],
    functions_by_file: dict[tuple[str, str], list[Any]],
) -> _PythonScope:
    collector = _ScopeBindingCollector(
        file_symbols=file_symbols,
        import_targets=import_targets,
        functions_by_file=functions_by_file,
    )

    if owner is not None:
        arguments = [
            *owner.args.posonlyargs,
            *owner.args.args,
            *owner.args.kwonlyargs,
        ]
        if owner.args.vararg is not None:
            arguments.append(owner.args.vararg)
        if owner.args.kwarg is not None:
            arguments.append(owner.args.kwarg)
        for argument in arguments:
            collector.bind_parameter(argument.arg, owner.lineno)

    for statement in body:
        collector.visit(statement)

    for events in collector.scope.bindings.values():
        events.sort(key=lambda event: event.line)
    return collector.scope


def _python_scopes(
    tree: ast.AST,
    *,
    file_symbols: list[Any],
    import_targets: dict[str, str],
    functions_by_file: dict[tuple[str, str], list[Any]],
) -> tuple[_PythonScope, dict[Any, _PythonScope]]:
    module_scope = _build_python_scope(
        getattr(tree, "body", ()),
        owner=None,
        file_symbols=file_symbols,
        import_targets=import_targets,
        functions_by_file=functions_by_file,
    )

    nodes = _function_nodes(tree)
    scopes: dict[Any, _PythonScope] = {}
    ordered_nodes = sorted(
        nodes,
        key=lambda node: (
            node.lineno,
            -(node.end_lineno or node.lineno),
        ),
    )

    for node in ordered_nodes:
        ancestors = [
            candidate
            for candidate in nodes
            if candidate is not node
            and candidate.lineno <= node.lineno
            and node.end_lineno is not None
            and candidate.end_lineno is not None
            and node.end_lineno <= candidate.end_lineno
            and candidate in scopes
        ]
        parent_scope = module_scope
        if ancestors:
            parent = min(
                ancestors,
                key=lambda candidate: (
                    candidate.end_lineno - candidate.lineno
                ),
            )
            parent_scope = scopes[parent]

        scope = _build_python_scope(
            node.body,
            owner=node,
            file_symbols=file_symbols,
            import_targets=import_targets,
            functions_by_file=functions_by_file,
        )
        scope.parent = parent_scope
        scopes[node] = scope

    return module_scope, scopes


def _latest_binding(
    scope: _PythonScope,
    name: str,
    line: int | None,
) -> _NameBinding | None:
    candidates = [
        binding
        for binding in scope.bindings.get(name, ())
        if line is None or binding.line <= line
    ]
    return max(candidates, key=lambda binding: binding.line, default=None)


def _binding_target(binding: _NameBinding | None) -> Any | None:
    if binding is None:
        return None
    if binding.kind in ("import", "definition"):
        return binding.target_symbol
    return None


def _resolve_scoped_name(
    name: str,
    line: int,
    scope: _PythonScope,
    module_scope: _PythonScope,
) -> Any | None:
    current: _PythonScope | None = scope
    while current is not None and current is not module_scope:
        local_binding = _latest_binding(current, name, line)
        if name in current.global_names and local_binding is None:
            return _binding_target(
                _latest_binding(module_scope, name, None)
            )
        if name in current.nonlocal_names and local_binding is None:
            current = current.parent
            continue
        if name in current.local_names:
            return _binding_target(local_binding)
        current = current.parent

    if name in module_scope.local_names:
        return _binding_target(
            _latest_binding(module_scope, name, None)
        )
    return None


def _annotation_class_names(annotation: ast.AST | None) -> set[str]:
    if annotation is None:
        return set()

    if isinstance(annotation, ast.Constant) and isinstance(
        annotation.value, str
    ):
        return set(re.findall(r"[A-Za-z_]\w*", annotation.value))

    names = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _callable_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _inferred_class_names(
    value: ast.AST,
    environment: dict[str, set[str]],
) -> set[str]:
    if isinstance(value, ast.Call):
        name = _callable_name(value.func)
        return {name} if name else set()
    if isinstance(value, ast.Name):
        return set(environment.get(value.id, ()))
    if isinstance(value, ast.BoolOp):
        names: set[str] = set()
        for item in value.values:
            names |= _inferred_class_names(item, environment)
        return names
    if isinstance(value, ast.IfExp):
        return _inferred_class_names(
            value.body, environment
        ) | _inferred_class_names(value.orelse, environment)
    return set()


def _update_local_types(
    node: ast.AST,
    environment: dict[str, set[str]],
) -> None:
    if isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
    ):
        return

    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names = _annotation_class_names(node.annotation)
        if node.value is not None:
            names |= _inferred_class_names(node.value, environment)
        if names:
            environment[node.target.id] = names
        return

    if isinstance(node, ast.Assign):
        names = _inferred_class_names(node.value, environment)
        if names:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    environment[target.id] = set(names)
        return

    for child in ast.iter_child_nodes(node):
        _update_local_types(child, environment)


def _function_argument_types(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, set[str]]:
    environment: dict[str, set[str]] = {}
    arguments = [
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg)

    for argument in arguments:
        names = _annotation_class_names(argument.annotation)
        if names:
            environment[argument.arg] = names

    return environment


def _function_local_types(node: ast.FunctionDef | ast.AsyncFunctionDef):
    environment = _function_argument_types(node)
    for statement in node.body:
        _update_local_types(statement, environment)

    return environment


def _function_nodes(tree: ast.AST):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _merged_local_types(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    nodes: list[ast.FunctionDef | ast.AsyncFunctionDef],
) -> dict[str, set[str]]:
    ancestors = [
        candidate
        for candidate in nodes
        if candidate is not node
        and candidate.lineno <= node.lineno
        and node.end_lineno is not None
        and candidate.end_lineno is not None
        and node.end_lineno <= candidate.end_lineno
    ]
    ancestors.sort(key=lambda candidate: (candidate.lineno, -candidate.end_lineno))

    environment: dict[str, set[str]] = {}
    for ancestor in ancestors:
        environment.update(_function_local_types(ancestor))
    # Las asignaciones del cuerpo se incorporan en orden al recorrerlo.
    environment.update(_function_argument_types(node))
    return environment


def _function_calls(node: ast.AST):
    if isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
    ):
        return
    if isinstance(node, ast.Call):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _function_calls(child)


def _record_calls(
    node: ast.AST,
    environment: dict[str, set[str]],
    calls: list[tuple[ast.Call, dict[str, set[str]]]],
) -> None:
    for call in _function_calls(node):
        calls.append((call, dict(environment)))


def _merge_environments(
    target: dict[str, set[str]],
    *environments: dict[str, set[str]],
) -> None:
    merged: dict[str, set[str]] = {}
    for environment in environments:
        for name, names in environment.items():
            merged.setdefault(name, set()).update(names)
    target.clear()
    target.update(merged)


def _collect_block_calls(
    statements: list[ast.stmt],
    environment: dict[str, set[str]],
    calls: list[tuple[ast.Call, dict[str, set[str]]]],
) -> None:
    for statement in statements:
        _collect_statement_calls(statement, environment, calls)


def _collect_statement_calls(
    statement: ast.stmt,
    environment: dict[str, set[str]],
    calls: list[tuple[ast.Call, dict[str, set[str]]]],
) -> None:
    if isinstance(
        statement,
        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
    ):
        return

    if isinstance(statement, ast.If):
        _record_calls(statement.test, environment, calls)
        body_environment = dict(environment)
        _collect_block_calls(statement.body, body_environment, calls)
        else_environment = dict(environment)
        _collect_block_calls(statement.orelse, else_environment, calls)
        _merge_environments(
            environment,
            body_environment,
            else_environment,
        )
        return

    if isinstance(statement, (ast.For, ast.AsyncFor)):
        _record_calls(statement.iter, environment, calls)
        entry_environment = dict(environment)
        body_environment = dict(environment)
        _collect_block_calls(statement.body, body_environment, calls)
        else_environment = dict(body_environment)
        _collect_block_calls(statement.orelse, else_environment, calls)
        _merge_environments(
            environment,
            entry_environment,
            body_environment,
            else_environment,
        )
        return

    if isinstance(statement, ast.While):
        _record_calls(statement.test, environment, calls)
        entry_environment = dict(environment)
        body_environment = dict(environment)
        _collect_block_calls(statement.body, body_environment, calls)
        else_environment = dict(body_environment)
        _collect_block_calls(statement.orelse, else_environment, calls)
        _merge_environments(
            environment,
            entry_environment,
            body_environment,
            else_environment,
        )
        return

    if isinstance(statement, (ast.Try, ast.TryStar)):
        body_environment = dict(environment)
        _collect_block_calls(statement.body, body_environment, calls)
        else_environment = dict(body_environment)
        _collect_block_calls(statement.orelse, else_environment, calls)

        handler_environments = []
        for handler in statement.handlers:
            handler_environment = dict(environment)
            if handler.type is not None:
                _record_calls(handler.type, handler_environment, calls)
            _collect_block_calls(
                handler.body,
                handler_environment,
                calls,
            )
            handler_environments.append(handler_environment)

        final_environment = dict(environment)
        _merge_environments(
            final_environment,
            else_environment,
            *handler_environments,
        )
        _collect_block_calls(
            statement.finalbody,
            final_environment,
            calls,
        )
        _merge_environments(environment, final_environment)
        return

    if isinstance(statement, (ast.With, ast.AsyncWith)):
        for item in statement.items:
            _record_calls(item.context_expr, environment, calls)
        entry_environment = dict(environment)
        body_environment = dict(environment)
        _collect_block_calls(statement.body, body_environment, calls)
        _merge_environments(
            environment,
            entry_environment,
            body_environment,
        )
        return

    if isinstance(statement, ast.Match):
        _record_calls(statement.subject, environment, calls)
        entry_environment = dict(environment)
        case_environments = []
        for case in statement.cases:
            case_environment = dict(environment)
            if case.guard is not None:
                _record_calls(case.guard, case_environment, calls)
            _collect_block_calls(case.body, case_environment, calls)
            case_environments.append(case_environment)
        _merge_environments(
            environment,
            entry_environment,
            *case_environments,
        )
        return

    _record_calls(statement, environment, calls)
    _update_local_types(statement, environment)


def _calls_with_local_types(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    nodes: list[ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[tuple[ast.Call, dict[str, set[str]]]]:
    environment = _merged_local_types(node, nodes)
    calls: list[tuple[ast.Call, dict[str, set[str]]]] = []
    _collect_block_calls(node.body, environment, calls)
    return calls


def _function_symbol(node, file_symbols):
    candidates = [
        symbol
        for symbol in file_symbols
        if symbol.name == node.name
        and symbol.start_line <= node.lineno <= symbol.end_line
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda symbol: symbol.end_line - symbol.start_line,
    )


def _enclosing_class_name(symbol, symbols_by_id: dict[str, Any]) -> str | None:
    parent = (
        symbols_by_id.get(symbol.parent_symbol_id)
        if symbol.parent_symbol_id
        else None
    )
    return parent.name if parent is not None and parent.kind == "class" else None


def _symbol_indexes(snapshot, symbols_by_id: dict[str, Any]):
    classes: dict[tuple[str, str], list[Any]] = {}
    functions_by_file: dict[tuple[str, str], list[Any]] = {}
    methods_by_parent: dict[tuple[str, str], list[Any]] = {}

    for symbol in getattr(snapshot, "symbols", ()):
        if symbol.kind == "class":
            classes.setdefault((symbol.project_id, symbol.name), []).append(
                symbol
            )
        if symbol.kind == "function":
            functions_by_file.setdefault((symbol.file_id, symbol.name), []).append(
                symbol
            )
        if symbol.kind == "method" and symbol.parent_symbol_id:
            methods_by_parent.setdefault(
                (symbol.parent_symbol_id, symbol.name), []
            ).append(symbol)

    return classes, functions_by_file, methods_by_parent


def _receiver_class_names(
    receiver: ast.AST,
    environment: dict[str, set[str]],
    self_class: str | None,
) -> set[str]:
    if isinstance(receiver, ast.Name):
        if receiver.id in ("self", "cls") and self_class:
            return {self_class}
        return set(environment.get(receiver.id, ()))
    return set()


def _resolve_python_call(
    call: ast.Call,
    project_id: str,
    environment: dict[str, set[str]],
    scope: _PythonScope,
    module_scope: _PythonScope,
    self_class: str | None,
    indexes,
) -> Any | None:
    classes, _, methods_by_parent = indexes
    function = call.func

    if isinstance(function, ast.Attribute):
        class_names = _receiver_class_names(
            function.value,
            environment,
            self_class,
        )
        if len(class_names) != 1:
            return None

        class_name = next(iter(class_names))
        class_candidates = classes.get((project_id, class_name), [])
        if len(class_candidates) != 1:
            return None

        method_candidates = methods_by_parent.get(
            (class_candidates[0].id, function.attr), []
        )
        return method_candidates[0] if len(method_candidates) == 1 else None

    if not isinstance(function, ast.Name):
        return None

    return _resolve_scoped_name(
        function.id,
        call.lineno,
        scope,
        module_scope,
    )


def _extract_python_call_relationships(
    snapshot,
    files_by_id: dict[str, Any],
    symbols_by_id: dict[str, Any],
    entrypoint_capability_by_symbol: dict[str, str],
) -> dict[str, list[CapabilityCall]]:
    """Construye llamadas resueltas; las importaciones no cuentan como llamadas."""
    calls_by_caller: dict[str, list[CapabilityCall]] = {}
    indexes = _symbol_indexes(snapshot, symbols_by_id)

    for source_file in getattr(snapshot, "files", ()):
        if (
            source_file.language != "python"
            or source_file.status != "processed"
            or not source_file.content
        ):
            continue

        try:
            tree = ast.parse(source_file.content, filename=source_file.path)
        except SyntaxError:
            continue

        file_symbols = [
            symbol
            for symbol in getattr(snapshot, "symbols", ())
            if symbol.file_id == source_file.id
        ]
        import_targets = _python_import_targets(
            source_file.id,
            getattr(snapshot, "relationships", ()),
        )
        nodes = _function_nodes(tree)
        module_scope, scopes_by_node = _python_scopes(
            tree,
            file_symbols=file_symbols,
            import_targets=import_targets,
            functions_by_file=indexes[1],
        )

        for node in nodes:
            caller = _function_symbol(node, file_symbols)
            if caller is None or node.end_lineno is None:
                continue

            scope = scopes_by_node.get(node)
            if scope is None:
                continue

            self_class = _enclosing_class_name(caller, symbols_by_id)
            seen: set[tuple[str, int, int]] = set()

            for call, environment in _calls_with_local_types(node, nodes):
                target = _resolve_python_call(
                    call,
                    source_file.project_id,
                    environment,
                    scope,
                    module_scope,
                    self_class,
                    indexes,
                )
                if target is None or target.id == caller.id:
                    continue

                key = (
                    target.id,
                    call.lineno,
                    call.end_lineno or call.lineno,
                )
                if key in seen:
                    continue
                seen.add(key)

                calls_by_caller.setdefault(caller.id, []).append(
                    CapabilityCall(
                        target_capability_id=(
                            entrypoint_capability_by_symbol.get(
                                target.id, f"symbol:{target.id}"
                            )
                        ),
                        target_symbol=target.qualified_name,
                        file_path=source_file.path,
                        start_line=call.lineno,
                        end_line=call.end_lineno or call.lineno,
                        snippet=_source_snippet(
                            source_file.content,
                            call.lineno,
                            call.end_lineno or call.lineno,
                        ),
                    )
                )

    return calls_by_caller


def _call_relationship_labels(
    calls: Iterable[CapabilityCall],
) -> list[str]:
    labels = []

    for call in calls:
        location = call.file_path
        if call.start_line is not None:
            location = f"{location}:{call.start_line}"
        labels.append(f"invoca: {call.target_symbol} ({location})")
        if len(labels) >= MAX_RELATIONSHIPS:
            break

    return labels


def extract_repository_capabilities(
    snapshot: Any,
    fragments: Iterable[CodeFragment],
) -> list[FunctionalCapability]:
    """Construye capacidades a partir de puntos de entrada, símbolos y relaciones."""
    files_by_id = {
        source_file.id: source_file
        for source_file in getattr(snapshot, "files", ())
    }
    symbols_by_id = {
        symbol.id: symbol
        for symbol in getattr(snapshot, "symbols", ())
    }
    evidence_by_id = {
        evidence.id: evidence
        for evidence in getattr(snapshot, "evidence", ())
    }
    relationships = tuple(getattr(snapshot, "relationships", ()))
    fragments_by_path = _fragment_index(fragments)
    capabilities: list[FunctionalCapability] = []
    entrypoint_symbol_ids: set[str] = set()
    entrypoint_capability_by_symbol = {
        entrypoint.symbol_id: f"entrypoint:{entrypoint.id}"
        for entrypoint in getattr(snapshot, "entrypoints", ())
        if entrypoint.symbol_id
    }
    calls_by_caller = _extract_python_call_relationships(
        snapshot,
        files_by_id,
        symbols_by_id,
        entrypoint_capability_by_symbol,
    )
    resolved_target_symbol_ids = {
        call.target_capability_id.removeprefix("symbol:")
        for calls in calls_by_caller.values()
        for call in calls
        if call.target_capability_id.startswith("symbol:")
    }

    for entrypoint in getattr(snapshot, "entrypoints", ()):
        if entrypoint.symbol_id:
            entrypoint_symbol_ids.add(entrypoint.symbol_id)
        calls = calls_by_caller.get(entrypoint.symbol_id, ())
        import_labels = (
            _relationship_labels(
                relationships,
                entrypoint.file_id,
                files_by_id,
            )
            if entrypoint.file_id
            else []
        )

        evidence = [
            _evidence_location(
                evidence_by_id[evidence_id],
                files_by_id,
                symbols_by_id,
                fragments_by_path,
                entrypoint.symbol_id,
            )
            for evidence_id in entrypoint.evidence_ids
            if evidence_id in evidence_by_id
        ]

        symbol = (
            symbols_by_id.get(entrypoint.symbol_id)
            if entrypoint.symbol_id
            else None
        )
        if symbol is not None:
            evidence.extend(
                _evidence_location(
                    evidence_by_id[evidence_id],
                    files_by_id,
                    symbols_by_id,
                    fragments_by_path,
                    symbol.id,
                )
                for evidence_id in symbol.evidence_ids
                if evidence_id in evidence_by_id
            )

        route_label = ""
        if entrypoint.http_method and entrypoint.route:
            route_label = (
                f" {entrypoint.http_method.upper()} {entrypoint.route}"
            )

        capabilities.append(
            FunctionalCapability(
                capability_id=f"entrypoint:{entrypoint.id}",
                name=entrypoint.name,
                kind=entrypoint.kind,
                description=(
                    f"Punto de entrada {entrypoint.kind}{route_label} "
                    f"detectado en {entrypoint.target}."
                ),
                detection=entrypoint.detection,
                http_method=entrypoint.http_method,
                route=entrypoint.route,
                evidence=_deduplicate_evidence(evidence),
                relationships=[
                    *import_labels,
                    *_call_relationship_labels(calls),
                ],
                calls=list(calls),
                limitations=list(entrypoint.limitations),
            )
        )

    symbol_candidates = []
    for symbol in getattr(snapshot, "symbols", ()):
        if symbol.id in entrypoint_symbol_ids:
            continue
        if symbol.kind not in ("function", "method", "class"):
            continue
        if (
            symbol.name.startswith("_")
            and symbol.id not in resolved_target_symbol_ids
        ):
            continue
        source_file = files_by_id.get(symbol.file_id)
        if source_file is None or _is_test_path(source_file.path):
            continue
        symbol_candidates.append(symbol)

    symbol_candidates.sort(
        key=lambda symbol: (
            files_by_id[symbol.file_id].path,
            symbol.start_line,
            symbol.qualified_name,
        )
    )

    for symbol in symbol_candidates[:MAX_SYMBOL_CAPABILITIES]:
        source_file = files_by_id[symbol.file_id]
        calls = calls_by_caller.get(symbol.id, ())
        evidence = [
            _evidence_location(
                evidence_by_id[evidence_id],
                files_by_id,
                symbols_by_id,
                fragments_by_path,
                symbol.id,
            )
            for evidence_id in symbol.evidence_ids
            if evidence_id in evidence_by_id
        ]
        capabilities.append(
            FunctionalCapability(
                capability_id=f"symbol:{symbol.id}",
                name=symbol.qualified_name,
                kind=symbol.kind,
                description=(
                    f"Símbolo {symbol.kind} '{symbol.qualified_name}' "
                    f"definido en {source_file.path}."
                ),
                detection="observed",
                evidence=_deduplicate_evidence(evidence),
                relationships=[
                    *_relationship_labels(
                        relationships,
                        symbol.file_id,
                        files_by_id,
                    ),
                    *_call_relationship_labels(calls),
                ],
                calls=list(calls),
            )
        )

    return capabilities


def _deduplicate_evidence(
    evidence: Iterable[EvidenceLocation],
) -> list[EvidenceLocation]:
    unique = {}
    for item in evidence:
        key = (
            item.file_path,
            item.start_line,
            item.end_line,
            item.symbol,
            item.fragment_id,
        )
        unique[key] = item
    return list(unique.values())


def _reference_kind(line: str, heading: re.Match | None) -> str:
    """Clasifica una mención como definición, correspondencia o referencia."""
    if heading is not None:
        return "definition"
    stripped = line.strip()
    if "|" in stripped or HTTP_METHOD_RE.search(stripped) or ROUTE_PATH_RE.search(stripped):
        return "mapping"
    return "mention"


def _heading_title(heading_text: str, requirement_id: str) -> str | None:
    """Devuelve el título del encabezado, sin repetir el identificador."""
    match = re.match(
        rf"^{re.escape(requirement_id)}\s*[:\-–—]?\s*",
        heading_text,
    )
    text = (
        heading_text[match.end():] if match else heading_text
    ).strip()
    return text or None


def _section_end_line(
    lines: list[str],
    heading_index: int,
    heading_level: int,
) -> int:
    """Calcula la última línea de la sección abierta por un encabezado."""
    for index in range(heading_index + 1, len(lines)):
        heading = MARKDOWN_HEADING_RE.match(lines[index])
        if heading is not None and len(heading.group("level")) <= heading_level:
            return index
    return len(lines)


def extract_document_references(
    snapshot: Any,
) -> list[DocumentReference]:
    """Indexa los requisitos citados por los documentos Markdown procesados.

    Cada ocurrencia de un identificador produce una referencia verificable:
    los encabezados abarcan su sección completa y el resto de menciones
    quedan limitadas a la línea donde aparecen.
    """
    references: list[DocumentReference] = []
    seen: set[tuple[str, str, int, int]] = set()

    for source_file in getattr(snapshot, "files", ()):
        if (
            source_file.language != DOCUMENT_LANGUAGE
            or source_file.status != "processed"
            or not source_file.content
        ):
            continue

        lines = source_file.content.splitlines()
        for index, line in enumerate(lines):
            identifiers = REQUIREMENT_ID_RE.findall(line)
            if not identifiers:
                continue

            heading = MARKDOWN_HEADING_RE.match(line)
            reference_kind = _reference_kind(line, heading)
            if heading is not None:
                start_line = index + 1
                end_line = _section_end_line(
                    lines,
                    index,
                    len(heading.group("level")),
                )
            else:
                start_line = end_line = index + 1

            for requirement_id in identifiers:
                key = (requirement_id, source_file.path, start_line, end_line)
                if key in seen:
                    continue
                seen.add(key)
                references.append(
                    DocumentReference(
                        requirement_id=requirement_id,
                        document_path=source_file.path,
                        start_line=start_line,
                        end_line=end_line,
                        title=(
                            _heading_title(
                                heading.group("text"),
                                requirement_id,
                            )
                            if heading is not None
                            else None
                        ),
                        reference_kind=reference_kind,
                    )
                )
                if len(references) >= MAX_DOCUMENT_REFERENCES:
                    return references

    return references


def extract_fragment_capabilities(
    fragments: Iterable[CodeFragment],
) -> list[FunctionalCapability]:
    """Recupera capacidades básicas cuando solo se proporcionan fragmentos."""
    capabilities: list[FunctionalCapability] = []
    seen: set[tuple[str, int]] = set()

    for fragment in fragments:
        match = FRAGMENT_PATH_RE.match(fragment.file_path)
        path = match.group(1) if match else fragment.file_path
        offset = int(match.group(2)) - 1 if match else 0

        for decorator_match in PYTHON_DECORATOR_RE.finditer(fragment.code):
            line = fragment.code.count("\n", 0, decorator_match.start()) + 1
            tail = fragment.code[decorator_match.end() :]
            function_match = PYTHON_DEF_RE.search(tail)
            function_name = (
                function_match.group(1)
                if function_match is not None
                else decorator_match.group(1)
            )
            method = decorator_match.group(1).upper()
            if method == "ROUTE":
                method = "GET"
            route = decorator_match.group(3)
            key = (f"{path}:{function_name}", line)
            if key in seen:
                continue
            seen.add(key)
            capabilities.append(
                FunctionalCapability(
                    capability_id=(
                        f"fragment:{fragment.fragment_id}:{line}:"
                        f"{function_name}"
                    ),
                    name=function_name,
                    kind="http_endpoint",
                    description=(
                        f"Endpoint {method} {route} detectado en {path}."
                    ),
                    detection="observed",
                    http_method=method,
                    route=route,
                    evidence=[
                        EvidenceLocation(
                            file_path=path,
                            start_line=offset + line,
                            end_line=offset + line,
                            symbol=function_name,
                            fragment_id=fragment.fragment_id,
                            snippet=fragment.code,
                        )
                    ],
                )
            )

        for regex, kind in (
            (PYTHON_CLASS_RE, "class"),
            (PYTHON_DEF_RE, "function"),
        ):
            for symbol_match in regex.finditer(fragment.code):
                name = symbol_match.group(1)
                if name.startswith("_"):
                    continue
                line = fragment.code.count("\n", 0, symbol_match.start()) + 1
                key = (f"{path}:{name}", line)
                if key in seen:
                    continue
                seen.add(key)
                capabilities.append(
                    FunctionalCapability(
                        capability_id=(
                            f"fragment:{fragment.fragment_id}:{line}:{name}"
                        ),
                        name=name,
                        kind=kind,
                        description=(
                            f"Símbolo {kind} '{name}' detectado en {path}."
                        ),
                        detection="observed",
                        evidence=[
                            EvidenceLocation(
                                file_path=path,
                                start_line=offset + line,
                                end_line=offset + line,
                                symbol=name,
                                fragment_id=fragment.fragment_id,
                                snippet=fragment.code,
                            )
                        ],
                    )
                )
                if len(capabilities) >= MAX_SYMBOL_CAPABILITIES:
                    break

        if PYTHON_MAIN_RE.search(fragment.code):
            line = fragment.code.count(
                "\n", 0, PYTHON_MAIN_RE.search(fragment.code).start()
            ) + 1
            capabilities.append(
                FunctionalCapability(
                    capability_id=(
                        f"fragment:{fragment.fragment_id}:{line}:__main__"
                    ),
                    name="__main__",
                    kind="application",
                    description=f"Entrada de aplicación en {path}.",
                    detection="inferred",
                    evidence=[
                        EvidenceLocation(
                            file_path=path,
                            start_line=offset + line,
                            end_line=offset + line,
                            fragment_id=fragment.fragment_id,
                            snippet=fragment.code,
                        )
                    ],
                )
            )

        if len(capabilities) >= MAX_SYMBOL_CAPABILITIES:
            break

    return capabilities


def _is_stub_statement(line: str) -> bool:
    if (
        PYTHON_PASS_RE.match(line)
        or PYTHON_ELLIPSIS_STATEMENT_RE.match(line)
        or PYTHON_NOT_IMPLEMENTED_RE.match(line)
    ):
        return True

    throw_match = JS_THROW_RE.match(line)
    return bool(
        throw_match is not None
        and NOT_IMPLEMENTED_MESSAGE_RE.search(throw_match.group("message"))
    )


def _matching_delimiter(
    text: str,
    start: int,
    opener: str,
    closer: str,
) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _python_inline_body(line: str) -> str:
    open_paren = line.find("(")
    close_paren = _matching_delimiter(line, open_paren, "(", ")")
    if close_paren == -1:
        return ""
    colon_index = line.find(":", close_paren + 1)
    if colon_index == -1:
        return ""
    return line[colon_index + 1 :].strip()


def _javascript_inline_body(line: str) -> str:
    open_paren = line.find("(")
    close_paren = _matching_delimiter(line, open_paren, "(", ")")
    if close_paren == -1:
        return ""
    open_brace = line.find("{", close_paren + 1)
    if open_brace == -1:
        return ""
    close_brace = line.rfind("}")
    if close_brace <= open_brace:
        return ""
    return line[open_brace + 1 : close_brace].strip()


def _inline_declaration_body(line: str) -> str | None:
    if PYTHON_INLINE_DEF_RE.match(line):
        return _python_inline_body(line)
    if JS_INLINE_FUNCTION_RE.match(line):
        return _javascript_inline_body(line)
    return None


def _looks_like_stub(snippets: str) -> bool:
    body_lines = []
    docstring_delimiter: str | None = None
    in_block_comment = False

    for line in snippets.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if docstring_delimiter is not None:
            if docstring_delimiter in stripped:
                docstring_delimiter = None
            continue

        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue

        if stripped.startswith(("#", "//")):
            continue

        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block_comment = True
            continue

        docstring_match = PYTHON_DOCSTRING_START_RE.match(stripped)
        if docstring_match is not None:
            delimiter = docstring_match.group(1)
            if delimiter not in stripped[docstring_match.end() :]:
                docstring_delimiter = delimiter
            continue

        if stripped.startswith("*"):
            continue

        inline_body = _inline_declaration_body(stripped)
        if inline_body is not None:
            if not inline_body:
                continue
            if inline_body.startswith(("#", "//", "/*")):
                continue
            if PYTHON_DOCSTRING_START_RE.match(inline_body) is not None:
                continue
            stripped = inline_body

        body_lines.append(stripped)

    if not body_lines:
        return True

    meaningful = [
        line
        for line in body_lines
        if not _is_stub_statement(line)
        and not line.startswith(
            (
                "def ",
                "async def ",
                "class ",
                "function ",
                "async function ",
                "export function ",
                "@",
            )
        )
        and line not in ("{", "}", "};")
    ]
    return not meaningful


def _evidence_reference(capability: FunctionalCapability) -> str:
    references = []
    for evidence in capability.evidence[:2]:
        if evidence.start_line and evidence.end_line:
            references.append(
                f"{evidence.file_path}:{evidence.start_line}-{evidence.end_line}"
            )
        else:
            references.append(evidence.file_path)
    return ", ".join(references) if references else "sin evidencia retenida"


def _has_symbol_evidence(capability: FunctionalCapability) -> bool:
    return any(item.symbol for item in capability.evidence)


def _has_internal_calls(capability: FunctionalCapability) -> bool:
    return bool(capability.calls)


def _incomplete_call_paths(
    capability: FunctionalCapability,
    capabilities_by_id: dict[str, FunctionalCapability],
    stub_by_id: dict[str, bool],
) -> list[tuple[list[CapabilityCall], FunctionalCapability]]:
    """Sigue solo llamadas resueltas hasta encontrar una implementación esqueleto."""
    paths: list[tuple[list[CapabilityCall], FunctionalCapability]] = []

    def visit(
        calls: Iterable[CapabilityCall],
        current_path: list[CapabilityCall],
        active: set[str],
    ) -> None:
        for call in calls:
            target_id = call.target_capability_id
            if not target_id or target_id in active:
                continue
            target = capabilities_by_id.get(target_id)
            if target is None:
                continue

            path = [*current_path, call]
            if stub_by_id.get(target_id, False):
                paths.append((path, target))
                continue

            visit(
                target.calls,
                path,
                active | {target_id},
            )

    visit(capability.calls, [], {capability.capability_id})
    return paths


def _propagation_reason(
    propagations: list[tuple[list[CapabilityCall], FunctionalCapability]],
) -> str:
    path, target = propagations[0]
    first_call = path[0]
    location = first_call.file_path
    if first_call.start_line is not None:
        location = f"{location}:{first_call.start_line}"

    if len(path) == 1:
        return (
            f"invoca directamente a '{target.name}' en {location}, cuya "
            "implementación es un esqueleto"
        )

    chain = " -> ".join(call.target_symbol for call in path)
    return (
        f"invoca a '{first_call.target_symbol}' en {location} y la cadena "
        f"resuelta {chain} termina en '{target.name}', cuya implementación "
        "es un esqueleto"
    )


def _propagation_evidence(
    propagations: list[tuple[list[CapabilityCall], FunctionalCapability]],
) -> list[EvidenceLocation]:
    evidence = []

    for path, target in propagations:
        for call in path:
            evidence.append(
                EvidenceLocation(
                    file_path=call.file_path,
                    start_line=call.start_line,
                    end_line=call.end_line,
                    symbol=call.target_symbol,
                    snippet=call.snippet,
                )
            )
        evidence.extend(target.evidence)

    return evidence


def _classify_completeness(
    capability: FunctionalCapability,
    is_stub: bool,
    propagations: list[tuple[list[CapabilityCall], FunctionalCapability]],
) -> FindingClassification:
    if not capability.evidence:
        return "no_verificado"
    if capability.detection == "inferred":
        return "probable"
    if is_stub:
        return "probable"
    if propagations:
        return "probable"
    if capability.kind in ENTRYPOINT_KINDS and not _has_symbol_evidence(
        capability
    ):
        return "probable"
    return "confirmado"


def _classify_correction(
    capability: FunctionalCapability,
    is_stub: bool,
    propagations: list[tuple[list[CapabilityCall], FunctionalCapability]],
) -> FindingClassification:
    if not capability.evidence:
        return "no_verificado"
    if is_stub:
        return "no_verificado"
    if propagations:
        return "no_verificado"
    if capability.detection == "inferred":
        return "probable"
    if capability.kind in ENTRYPOINT_KINDS and not _has_symbol_evidence(
        capability
    ):
        return "probable"
    return "confirmado"


def _classify_pertinence(
    capability: FunctionalCapability,
) -> FindingClassification:
    if not capability.evidence:
        return "no_verificado"
    if (
        capability.kind in ENTRYPOINT_KINDS
        and capability.detection == "observed"
    ):
        return "confirmado"
    if capability.detection == "inferred":
        return "probable"
    if _has_internal_calls(capability):
        return "confirmado"
    if _has_symbol_evidence(capability):
        return "probable"
    return "no_verificado"


def _justification(
    capability: FunctionalCapability,
    attribute: SubattributeName,
    classification: FindingClassification,
    is_stub: bool,
    propagations: list[tuple[list[CapabilityCall], FunctionalCapability]],
) -> str:
    reference = _evidence_reference(capability)

    if attribute == "completitud":
        if classification == "confirmado":
            return (
                f"La capacidad '{capability.name}' presenta evidencia "
                f"observada en {reference} y una implementación estática no "
                "vacía."
            )
        if classification == "probable":
            reason = (
                _propagation_reason(propagations)
                if propagations
                else "la detección es inferida"
                if capability.detection == "inferred"
                else "la implementación parece un esqueleto o no puede "
                "resolverse por completo"
                if is_stub
                else "el punto de entrada no expone un símbolo de "
                "implementación resoluble"
            )
            return (
                f"La capacidad '{capability.name}' está declarada en "
                f"{reference}, pero {reason}."
            )
        return (
            f"No hay evidencia de código retenida suficiente para la "
            f"capacidad '{capability.name}'."
        )

    if attribute == "correccion":
        if classification == "confirmado":
            return (
                f"La implementación de '{capability.name}' en {reference} no "
                "presenta marcadores de esqueleto ni contradicciones estáticas "
                "evidentes. No se dispone de especificaciones para demostrar "
                "corrección funcional."
            )
        if propagations:
            return (
                f"La capacidad '{capability.name}' en {reference} "
                f"{_propagation_reason(propagations)}; por eso no puede "
                "confirmarse su corrección."
            )
        if classification == "probable":
            return (
                f"La implementación de '{capability.name}' en {reference} es "
                "parcial o depende de comportamiento no visible; no permite "
                "confirmar su corrección."
            )
        if is_stub:
            return (
                f"La capacidad '{capability.name}' en {reference} parece un "
                "esqueleto o marcador de no implementación; no puede evaluarse "
                "su corrección."
            )
        return (
            f"No hay código suficiente para evaluar la corrección de "
            f"'{capability.name}'."
        )

    if classification == "confirmado":
        return (
            f"La capacidad '{capability.name}' es un punto de entrada "
            f"observado o participa en llamadas internas resueltas del "
            f"repositorio ({reference})."
        )
    if classification == "probable":
        return (
            f"La capacidad '{capability.name}' está respaldada por evidencia "
            f"en {reference}, pero no se demostró su uso dentro del "
            "repositorio."
        )
    return (
        f"La capacidad '{capability.name}' carece de evidencia o relaciones "
        "que permitan vincularla con el comportamiento del sistema."
    )


def _transitive_call_evidence(
    capability: FunctionalCapability,
    capabilities_by_id: dict[str, FunctionalCapability],
) -> list[EvidenceLocation]:
    """Reúne la evidencia de las capacidades llamadas, siguiendo cadenas resueltas."""
    evidence: list[EvidenceLocation] = []
    seen: set[str] = set()

    def visit(current: FunctionalCapability, active: set[str]) -> None:
        for call in current.calls:
            target_id = call.target_capability_id
            if not target_id or target_id in active:
                continue
            target = capabilities_by_id.get(target_id)
            if target is None:
                continue
            if target_id not in seen:
                seen.add(target_id)
                evidence.extend(target.evidence)
            visit(target, active | {target_id})

    visit(capability, {capability.capability_id})
    return evidence


def _requirement_identifiers(
    evidence: Iterable[EvidenceLocation],
) -> set[str]:
    """Extrae los identificadores de requisitos citados por la evidencia."""
    identifiers: set[str] = set()
    for item in evidence:
        if item.snippet:
            identifiers.update(REQUIREMENT_ID_RE.findall(item.snippet))
    return identifiers


def _matching_document_references(
    document_references: list[DocumentReference],
    evidence: list[EvidenceLocation],
) -> list[DocumentReference]:
    """Selecciona las referencias de los requisitos citados por la evidencia."""
    identifiers = _requirement_identifiers(evidence)
    if not identifiers:
        return []
    return sorted(
        (
            reference
            for reference in document_references
            if reference.requirement_id in identifiers
        ),
        key=lambda reference: (
            REFERENCE_KIND_ORDER.get(reference.reference_kind, 3),
            reference.document_path,
            reference.start_line,
        ),
    )


def evaluate_capabilities(
    capabilities: Iterable[FunctionalCapability],
    document_references: Iterable[DocumentReference] | None = None,
) -> list[CapabilityFinding]:
    """Evalúa completitud, corrección y pertinencia con criterios explícitos."""
    capability_list = list(capabilities)
    capabilities_by_id = {
        capability.capability_id: capability
        for capability in capability_list
    }
    references = list(document_references or [])
    stub_by_id = {}

    for capability in capability_list:
        snippets = "\n".join(
            item.snippet or "" for item in capability.evidence
        )
        stub_by_id[capability.capability_id] = (
            _looks_like_stub(snippets) if snippets else False
        )

    findings = []

    for capability in capability_list:
        is_stub = stub_by_id[capability.capability_id]
        propagations = _incomplete_call_paths(
            capability,
            capabilities_by_id,
            stub_by_id,
        )
        evidence = list(capability.evidence)
        if propagations:
            evidence = _deduplicate_evidence(
                [*evidence, *_propagation_evidence(propagations)]
            )
        classifications = {
            "completitud": _classify_completeness(
                capability,
                is_stub,
                propagations,
            ),
            "correccion": _classify_correction(
                capability,
                is_stub,
                propagations,
            ),
            "pertinencia": _classify_pertinence(capability),
        }

        reference_evidence = [
            *evidence,
            *_transitive_call_evidence(capability, capabilities_by_id),
        ]

        for attribute, classification in classifications.items():
            findings.append(
                CapabilityFinding(
                    finding_id=f"{capability.capability_id}:{attribute}",
                    capability_id=capability.capability_id,
                    capability_name=capability.name,
                    attribute=attribute,
                    classification=classification,
                    justification=_justification(
                        capability,
                        attribute,
                        classification,
                        is_stub,
                        propagations,
                    ),
                    criteria=ATTRIBUTE_CRITERIA[attribute][classification],
                    evidence=evidence,
                    document_references=(
                        _matching_document_references(references, reference_evidence)
                    ),
                )
            )

    return findings


def build_subattribute_summaries(
    findings: Iterable[CapabilityFinding],
) -> list[SubattributeSummary]:
    summaries = []

    for attribute in ("completitud", "correccion", "pertinencia"):
        attribute_findings = [
            finding
            for finding in findings
            if finding.attribute == attribute
        ]
        confirmed = sum(
            finding.classification == "confirmado"
            for finding in attribute_findings
        )
        probable = sum(
            finding.classification == "probable"
            for finding in attribute_findings
        )
        unverified = sum(
            finding.classification == "no_verificado"
            for finding in attribute_findings
        )
        summaries.append(
            SubattributeSummary(
                attribute=attribute,
                evaluated_capabilities=len(attribute_findings),
                confirmed=confirmed,
                probable=probable,
                unverified=unverified,
                summary=(
                    f"{attribute.capitalize()}: {len(attribute_findings)} "
                    f"capacidades evaluadas, {confirmed} confirmadas, "
                    f"{probable} probables y {unverified} no verificadas."
                ),
            )
        )

    return summaries


def build_exploratory_limitations(
    input_data: FunctionalAdequacyInput,
    capabilities: list[FunctionalCapability],
    findings: list[CapabilityFinding],
) -> list[str]:
    limitations = list(BASE_EXPLORATORY_LIMITATIONS)

    if not input_data.code_fragments:
        limitations.append(
            "No se retuvieron fragmentos de código fuente compatibles en el "
            "repositorio analizado."
        )

    if not capabilities:
        limitations.append(
            "No se detectaron capacidades funcionales a partir de puntos de "
            "entrada, funciones, clases o relaciones."
        )
    elif not any(
        capability.kind in ENTRYPOINT_KINDS
        for capability in capabilities
    ):
        limitations.append(
            "No se detectaron puntos de entrada; las capacidades provienen "
            "únicamente de símbolos o fragmentos de código."
        )

    if any(
        finding.attribute == "completitud"
        and finding.classification == "probable"
        for finding in findings
    ):
        limitations.append(
            "Algunas capacidades parecen declaradas sin una implementación "
            "completa o resoluble estáticamente."
        )

    context = input_data.repository_context
    if context is not None:
        limitations.extend(context.analysis_limitations)
        limitations.extend(
            f"Incidente de análisis: {issue}"
            for issue in context.analysis_issues
        )

    return list(dict.fromkeys(limitations))


def is_stub_capability(capability: FunctionalCapability) -> bool:
    """Indica si la evidencia disponible solo contiene un esqueleto."""
    snippets = "\n".join(
        item.snippet or "" for item in capability.evidence
    )
    return bool(snippets) and _looks_like_stub(snippets)
