
"""Detección y evaluación estática de capacidades funcionales.

Este módulo reutiliza los hechos producidos por RepositoryAnalysisService.
No ejecuta el sistema analizado ni mide cobertura de pruebas.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .schemas import (
    CapabilityFinding,
    CodeFragment,
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

    for entrypoint in getattr(snapshot, "entrypoints", ()):
        if entrypoint.symbol_id:
            entrypoint_symbol_ids.add(entrypoint.symbol_id)

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
                relationships=(
                    _relationship_labels(
                        relationships,
                        entrypoint.file_id,
                        files_by_id,
                    )
                    if entrypoint.file_id
                    else []
                ),
                limitations=list(entrypoint.limitations),
            )
        )

    symbol_candidates = []
    for symbol in getattr(snapshot, "symbols", ()):
        if symbol.id in entrypoint_symbol_ids:
            continue
        if symbol.kind not in ("function", "method", "class"):
            continue
        if symbol.name.startswith("_"):
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
                relationships=_relationship_labels(
                    relationships,
                    symbol.file_id,
                    files_by_id,
                ),
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


def _has_internal_relationships(capability: FunctionalCapability) -> bool:
    return bool(capability.relationships)


def _classify_completeness(
    capability: FunctionalCapability,
    is_stub: bool,
) -> FindingClassification:
    if not capability.evidence:
        return "no_verificado"
    if capability.detection == "inferred":
        return "probable"
    if is_stub:
        return "probable"
    if capability.kind in ENTRYPOINT_KINDS and not _has_symbol_evidence(
        capability
    ):
        return "probable"
    return "confirmado"


def _classify_correction(
    capability: FunctionalCapability,
    is_stub: bool,
) -> FindingClassification:
    if not capability.evidence:
        return "no_verificado"
    if is_stub:
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
    if _has_internal_relationships(capability):
        return "confirmado"
    if _has_symbol_evidence(capability):
        return "probable"
    return "no_verificado"


def _justification(
    capability: FunctionalCapability,
    attribute: SubattributeName,
    classification: FindingClassification,
    is_stub: bool,
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
                "la detección es inferida"
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
            f"observado o participa en relaciones internas del repositorio "
            f"({reference})."
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


def evaluate_capabilities(
    capabilities: Iterable[FunctionalCapability],
) -> list[CapabilityFinding]:
    """Evalúa completitud, corrección y pertinencia con criterios explícitos."""
    findings = []

    for capability in capabilities:
        snippets = "\n".join(
            item.snippet or "" for item in capability.evidence
        )
        is_stub = _looks_like_stub(snippets) if snippets else False
        classifications = {
            "completitud": _classify_completeness(capability, is_stub),
            "correccion": _classify_correction(capability, is_stub),
            "pertinencia": _classify_pertinence(capability),
        }

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
                    ),
                    criteria=ATTRIBUTE_CRITERIA[attribute][classification],
                    evidence=list(capability.evidence),
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


def build_exploratory_recommendations(
    capabilities: list[FunctionalCapability],
    findings: list[CapabilityFinding],
) -> list[str]:
    recommendations = []

    if not capabilities:
        recommendations.append(
            "Proporcionar requisitos funcionales explícitos o revisar que el "
            "repositorio contenga código fuente compatible."
        )
    elif not any(
        capability.kind in ENTRYPOINT_KINDS
        for capability in capabilities
    ):
        recommendations.append(
            "Documentar los puntos de entrada del sistema para mejorar la "
            "trazabilidad de las capacidades detectadas."
        )

    for finding in findings:
        if finding.attribute != "completitud":
            continue
        if finding.classification == "no_verificado":
            recommendations.append(
                f"Revisar manualmente la capacidad '{finding.capability_name}': "
                "no se dispone de evidencia suficiente."
            )
        elif finding.classification == "probable":
            recommendations.append(
                f"Verificar la implementación de la capacidad "
                f"'{finding.capability_name}': la evidencia es parcial."
            )

    recommendations.append(
        "Proporcionar especificaciones funcionales para evaluar el "
        "cumplimiento real y la corrección frente a requisitos."
    )

    return list(dict.fromkeys(recommendations))


def is_stub_capability(capability: FunctionalCapability) -> bool:
    """Indica si la evidencia disponible solo contiene un esqueleto."""
    snippets = "\n".join(
        item.snippet or "" for item in capability.evidence
    )
    return bool(snippets) and _looks_like_stub(snippets)
