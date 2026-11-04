
from __future__ import annotations

import asyncio
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.graph import END, StateGraph

from server.runtimes.direct import BaseAgent

from ...config.logs import get_logger
from ...config.tracing import traced_generate
from .config import FunctionalAdequacyConfig
from .exploratory import (
    CLASSIFICATION_CRITERIA,
    build_exploratory_limitations,
    build_exploratory_recommendations,
    build_subattribute_summaries,
    evaluate_capabilities,
    extract_fragment_capabilities,
)
from .schemas import (
    AuditMode,
    CapabilityFinding,
    CodeEvidence,
    FunctionalAdequacyInput,
    FunctionalAdequacyOutput,
    FunctionalCapability,
    RequirementResult,
    SubattributeSummary,
)

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger("functional-adequacy-agent")

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_FRAGMENT_PATH_RE = re.compile(r"^(.*):(\d+)-(\d+)$")
REQUIREMENTS_LIMITATIONS = [
    (
        "El puntaje representa únicamente los requisitos evaluados; no es una "
        "medida de cobertura funcional del repositorio."
    ),
    (
        "La clasificación depende de la evidencia recuperada y del modelo; no "
        "sustituye una validación independiente ni la ejecución de pruebas."
    ),
]

SBERT_DEPENDENCY_ERROR = (
    "La recuperación semántica del modo basado en requisitos requiere la "
    "dependencia opcional 'sentence-transformers'. Instálela para habilitar "
    "ese modo; el modo exploratorio no la necesita."
)
SBERT_MODEL_ERROR = (
    "No se pudo cargar el modelo de recuperación semántica "
    f"'{FunctionalAdequacyConfig().embedding_model}'. Verifique la instalación de sentence-transformers y la "
    "disponibilidad del modelo."
)


class SemanticRetrievalUnavailableError(RuntimeError):
    """The optional semantic retrieval stack cannot be used."""


@lru_cache(maxsize=1)
def _load_sentence_transformers() -> tuple[Any, Any]:
    """Import the optional retrieval stack only when requirements need it."""
    try:
        from sentence_transformers import SentenceTransformer, util
    except ImportError as error:
        raise SemanticRetrievalUnavailableError(SBERT_DEPENDENCY_ERROR) from error
    return SentenceTransformer, util


@lru_cache(maxsize=4)
def _get_sbert_model(model_name: str = FunctionalAdequacyConfig().embedding_model) -> SentenceTransformer:
    """Load SBERT once and reuse it across requirement-based executions."""
    sentence_transformer, _ = _load_sentence_transformers()
    try:
        return sentence_transformer(model_name)
    except Exception as error:
        raise SemanticRetrievalUnavailableError(SBERT_MODEL_ERROR) from error


def _cosine_similarity(requirement_vectors: Any, code_vectors: Any) -> Any:
    """Compute cosine similarity without importing SBERT at module load."""
    _, util = _load_sentence_transformers()
    return util.cos_sim(requirement_vectors, code_vectors)


def _response_text(response: object) -> str:
    """Normalize responses from supported LLM providers."""
    if isinstance(response, str):
        return response

    content = getattr(response, "content", None)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            if isinstance(item, dict)
            else str(item)
            for item in content
        )

    text = getattr(response, "text", None)

    if isinstance(text, str):
        return text

    return str(response)


def _code_evidence(
    fragment,
    similarity: float,
    symbol: str | None = None,
) -> CodeEvidence:
    match = _FRAGMENT_PATH_RE.match(fragment.file_path)

    return CodeEvidence(
        fragment_id=fragment.fragment_id,
        file_path=fragment.file_path,
        similarity=similarity,
        start_line=int(match.group(2)) if match else None,
        end_line=int(match.group(3)) if match else None,
        symbol=symbol,
        snippet=fragment.code,
    )


def _symbol_for_fragment(
    input_data: FunctionalAdequacyInput,
    fragment,
) -> str | None:
    context = input_data.repository_context
    match = _FRAGMENT_PATH_RE.match(fragment.file_path)

    if context is None or match is None:
        return None

    path = match.group(1)
    fragment_start = int(match.group(2))
    fragment_end = int(match.group(3))
    matching_symbols = set()

    for capability in context.capabilities:
        for evidence in capability.evidence:
            if evidence.file_path != path or evidence.symbol is None:
                continue
            evidence_start = evidence.start_line or 1
            evidence_end = evidence.end_line or evidence_start
            if (
                evidence_start <= fragment_end
                and fragment_start <= evidence_end
            ):
                matching_symbols.add(evidence.symbol)

    if len(matching_symbols) == 1:
        return next(iter(matching_symbols))

    return None


def _parse_json_response(response: object) -> dict[str, Any]:
    """Extract one JSON object from an LLM response."""
    text = _response_text(response).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)

        if match is None:
            raise ValueError("LLM response contains no JSON")

        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise TypeError("LLM response must be a JSON object")

    return data


class _FunctionalState(TypedDict, total=False):
    input_data: FunctionalAdequacyInput
    audit_mode: AuditMode
    candidates: dict[str, list[CodeEvidence]]
    results: list[RequirementResult]
    retrieval_error: str
    capabilities: list[FunctionalCapability]
    findings: list[CapabilityFinding]
    subattributes: list[SubattributeSummary]
    limitations: list[str]
    output: FunctionalAdequacyOutput


class FunctionalAdequacyAgent(
    BaseAgent[FunctionalAdequacyInput, FunctionalAdequacyOutput]
):
    """Audit functional requirements against supplied code evidence."""

    agent_type = "functional_adequacy"
    prompt_directory = Path(__file__).parent / "prompts"
    input_schema = FunctionalAdequacyInput
    output_schema = FunctionalAdequacyOutput
    config_type = FunctionalAdequacyConfig

    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config or self.config_type()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(_FunctionalState)

        from ...runtimes.invocation_reporting import phase_node

        graph.add_node("prepare", phase_node("prepare", self._prepare))
        graph.add_node("code_mapping", phase_node("code_mapping", self._code_mapping))
        graph.add_node("verify", phase_node("verify", self._verify))
        graph.add_node("build_results", phase_node("build_results", self._build_results))
        graph.add_node("exploratory_analysis", phase_node("exploratory_analysis", self._exploratory_analysis))
        graph.add_node(
            "build_exploratory_results",
            phase_node("build_exploratory_results", self._build_exploratory_results),
        )

        graph.set_entry_point("prepare")
        graph.add_conditional_edges(
            "prepare",
            self._select_audit_path,
            {
                "requirements_based": "code_mapping",
                "exploratory": "exploratory_analysis",
            },
        )
        graph.add_edge("code_mapping", "verify")
        graph.add_edge("verify", "build_results")
        graph.add_edge("build_results", END)
        graph.add_edge(
            "exploratory_analysis",
            "build_exploratory_results",
        )
        graph.add_edge("build_exploratory_results", END)

        return graph.compile()

    def _select_audit_path(self, state: _FunctionalState) -> str:
        return state.get("audit_mode", "requirements_based")

    async def _prepare(self, state: _FunctionalState) -> dict:
        input_data = state["input_data"]

        # Seleccionar el modo según la disponibilidad de requisitos.
        audit_mode: AuditMode = (
            "requirements_based"
            if input_data.requirements
            else "exploratory"
        )

        logger.info(
            "Preparing audit mode=%s with %d requirements and %d fragments",
            audit_mode,
            len(input_data.requirements),
            len(input_data.code_fragments),
        )

        return {
            "audit_mode": audit_mode,
            "candidates": {},
            "results": [],
            "retrieval_error": "",
        }

    async def _code_mapping(self, state: _FunctionalState) -> dict:
        # Embedding model loading/inference is CPU-bound and must not block
        # lifecycle callbacks or sibling attributes on the server event loop.
        return await asyncio.to_thread(self._retrieve_candidates, state)

    def _retrieve_candidates(self, state: _FunctionalState) -> dict:
        """Retrieve the configured number of code candidates per requirement."""
        input_data = state["input_data"]
        fragments = input_data.code_fragments

        if not input_data.requirements:
            return {"candidates": {}}

        if not fragments:
            return {
                "candidates": {
                    req.requirement_id: []
                    for req in input_data.requirements
                }
            }

        try:
            model = _get_sbert_model(self.config.embedding_model)

            requirement_texts = [
                req.description for req in input_data.requirements
            ]
            code_texts = [
                fragment.code for fragment in fragments
            ]

            requirement_vectors = model.encode(
                requirement_texts,
                convert_to_tensor=True,
            )
            code_vectors = model.encode(
                code_texts,
                convert_to_tensor=True,
            )

            similarity_matrix = _cosine_similarity(
                requirement_vectors,
                code_vectors,
            )
        except SemanticRetrievalUnavailableError as error:
            logger.warning(
                "Semantic retrieval unavailable for requirements-based audit: %s",
                error,
            )
            return {
                "candidates": {
                    req.requirement_id: []
                    for req in input_data.requirements
                },
                "retrieval_error": str(error),
            }

        candidates = {}

        for index, requirement in enumerate(input_data.requirements):
            scores = similarity_matrix[index]
            top_indices = [
                int(item)
                for item in scores.argsort(descending=True)[
                    :min(self.config.retrieval_top_k, len(fragments))
                ]
            ]

            # Priorizar evidencia explícita del decorador cuando el requisito lo menciona.
            if "app.get" in requirement.description.lower():
                matching_indices = [
                    fragment_index
                    for fragment_index, fragment in enumerate(fragments)
                    if "@app.get(" in fragment.code
                ]
                if matching_indices:
                    best_match = max(
                        matching_indices,
                        key=lambda fragment_index: float(scores[fragment_index]),
                    )
                    if best_match not in top_indices:
                        top_indices[-1] = best_match

            candidates[requirement.requirement_id] = [
                _code_evidence(
                    fragments[int(fragment_index)],
                    float(scores[int(fragment_index)]),
                    _symbol_for_fragment(
                        input_data,
                        fragments[int(fragment_index)],
                    ),
                )
                for fragment_index in top_indices
            ]

        return {"candidates": candidates}

    async def _verify(self, state: _FunctionalState) -> dict:
        """Use the LLM to assess each requirement against code evidence."""
        input_data = state["input_data"]
        candidates = state["candidates"]
        retrieval_error = state.get("retrieval_error", "")

        fragment_lookup = {
            fragment.fragment_id: fragment
            for fragment in input_data.code_fragments
        }

        results = []

        for requirement in input_data.requirements:
            evidence = candidates.get(requirement.requirement_id, [])

            if not evidence:
                if retrieval_error:
                    justification = (
                        "No se pudo recuperar evidencia de código: "
                        f"{retrieval_error}"
                    )
                elif not input_data.code_fragments:
                    justification = (
                        "No se proporcionaron fragmentos de código."
                    )
                else:
                    justification = (
                        "La recuperación semántica no encontró fragmentos "
                        "candidatos."
                    )
                results.append(
                    RequirementResult(
                        requirement_id=requirement.requirement_id,
                        description=requirement.description,
                        status="evidencia_insuficiente",
                        justification=justification,
                        evidence=[],
                    )
                )
                continue

            evidence_payload = [
                {
                    "fragment_id": item.fragment_id,
                    "file_path": item.file_path,
                    "code": fragment_lookup[item.fragment_id].code,
                    "similarity": item.similarity,
                }
                for item in evidence
            ]

            prompt = (
                f"{self.system_prompt()}\n\n"
                f"{self.user_prompt(
                    requirement_id=requirement.requirement_id,
                    requirement=requirement.description,
                    evidence=json.dumps(
                        evidence_payload,
                        ensure_ascii=False,
                    ),
                )}"
            )

            try:
                response = await traced_generate(self.model, prompt)
                parsed = _parse_json_response(response)

                status = parsed.get(
                    "status", "evidencia_insuficiente"
                )

                if status not in (
                    "cumple",
                    "no_cumple",
                    "evidencia_insuficiente",
                ):
                    raise ValueError("Invalid compliance status")

                justification = parsed.get("justification")

                if not isinstance(justification, str) or not justification.strip():
                    raise ValueError("Missing justification")

            except Exception as error:  # noqa: BLE001  # noqa: BLE001
                logger.warning(
                    "Verification failed for %s: %s",
                    requirement.requirement_id,
                    error,
                )
                status = "evidencia_insuficiente"
                justification = (
                    "No fue posible verificar el requisito con el LLM."
                )

            results.append(
                RequirementResult(
                    requirement_id=requirement.requirement_id,
                    description=requirement.description,
                    status=status,
                    justification=justification,
                    evidence=evidence,
                )
            )

        return {"results": results}

    async def _exploratory_analysis(self, state: _FunctionalState) -> dict:
        """Detecta capacidades y las evalúa sin requisitos explícitos."""
        input_data = state["input_data"]
        context = input_data.repository_context

        if context is not None and context.capabilities:
            capabilities = context.capabilities
        elif input_data.code_fragments:
            capabilities = extract_fragment_capabilities(
                input_data.code_fragments
            )
        else:
            capabilities = []

        findings = evaluate_capabilities(capabilities)
        subattributes = build_subattribute_summaries(findings)
        limitations = build_exploratory_limitations(
            input_data,
            capabilities,
            findings,
        )

        logger.info(
            "Exploratory analysis detected %d capabilities and %d findings",
            len(capabilities),
            len(findings),
        )

        return {
            "capabilities": capabilities,
            "findings": findings,
            "subattributes": subattributes,
            "limitations": limitations,
        }

    async def _build_exploratory_results(
        self,
        state: _FunctionalState,
    ) -> dict:
        """Construye el resultado exploratorio sin inventar cobertura."""
        capabilities = state.get("capabilities", [])
        findings = state.get("findings", [])
        subattributes = state.get("subattributes", [])
        limitations = state.get("limitations", [])

        output = FunctionalAdequacyOutput(
            audit_mode="exploratory",
            score=0.0,
            score_applicable=False,
            score_meaning=(
                "No aplica: no se proporcionaron requisitos funcionales, por "
                "lo que no se calcula un porcentaje de cumplimiento ni de "
                "cobertura."
            ),
            total_requirements=0,
            fulfilled_requirements=0,
            results=[],
            capabilities=capabilities,
            findings=findings,
            subattributes=subattributes,
            classification_criteria=CLASSIFICATION_CRITERIA,
            limitations=limitations,
            recommendations=build_exploratory_recommendations(
                capabilities,
                findings,
            ),
        )

        logger.info(
            "Exploratory functional adequacy completed: %d capabilities",
            len(capabilities),
        )

        return {"output": output}

    async def _build_results(self, state: _FunctionalState) -> dict:
        """Calculate coverage from verified requirement statuses."""
        results = state["results"]

        total = len(results)
        fulfilled = sum(
            result.status == "cumple"
            for result in results
        )

        score = (
            round((fulfilled / total) * 100, 2)
            if total
            else 0.0
        )

        recommendations = []

        for result in results:
            if result.status != "cumple":
                recommendations.append(
                    f"Revisar {result.requirement_id}: "
                    f"{result.justification}"
                )

        limitations = list(REQUIREMENTS_LIMITATIONS)
        retrieval_error = state.get("retrieval_error", "")

        if retrieval_error:
            limitations.append(retrieval_error)

        context = state["input_data"].repository_context

        if context is not None:
            limitations.extend(context.analysis_limitations)
            limitations.extend(context.analysis_issues)

        output = FunctionalAdequacyOutput(
            audit_mode="requirements_based",
            score=score,
            total_requirements=total,
            fulfilled_requirements=fulfilled,
            results=results,
            limitations=limitations,
            recommendations=recommendations,
        )

        logger.info(
            "Functional adequacy completed: %.2f%% (%d/%d)",
            score,
            fulfilled,
            total,
        )

        return {"output": output}

    async def run(
        self,
        input_data: FunctionalAdequacyInput,
    ) -> FunctionalAdequacyOutput:
        final_state = await self._graph.ainvoke({
            "input_data": input_data,
        })

        return final_state["output"]
