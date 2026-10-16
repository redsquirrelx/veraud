
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sentence_transformers import SentenceTransformer, util

from ...config.logs import get_logger
from ...config.tracing import traced_generate
from ..base import BaseAgent
from .config import FunctionalAdequacyConfig
from .schemas import (
    CodeEvidence,
    FunctionalAdequacyInput,
    FunctionalAdequacyOutput,
    RequirementResult,
)

logger = get_logger("functional-adequacy-agent")

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@lru_cache(maxsize=4)
def _get_sbert_model(model_name: str = FunctionalAdequacyConfig().embedding_model) -> SentenceTransformer:
    """Load SBERT once and reuse it across executions."""
    return SentenceTransformer(model_name)


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
    candidates: dict[str, list[CodeEvidence]]
    results: list[RequirementResult]
    output: FunctionalAdequacyOutput


class FunctionalAdequacyAgent(
    BaseAgent[FunctionalAdequacyInput, FunctionalAdequacyOutput]
):
    """Audit functional requirements against supplied code evidence."""

    agent_type = "functional_adequacy"
    input_schema = FunctionalAdequacyInput
    output_schema = FunctionalAdequacyOutput
    config_type = FunctionalAdequacyConfig

    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config or self.config_type()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(_FunctionalState)

        graph.add_node("prepare", self._prepare)
        graph.add_node("code_mapping", self._code_mapping)
        graph.add_node("verify", self._verify)
        graph.add_node("build_results", self._build_results)

        graph.set_entry_point("prepare")
        graph.add_edge("prepare", "code_mapping")
        graph.add_edge("code_mapping", "verify")
        graph.add_edge("verify", "build_results")
        graph.add_edge("build_results", END)

        return graph.compile()

    async def _prepare(self, state: _FunctionalState) -> dict:
        input_data = state["input_data"]

        logger.info(
            "Preparing %d requirements and %d fragments",
            len(input_data.requirements),
            len(input_data.code_fragments),
        )

        return {
            "candidates": {},
            "results": [],
        }

    async def _code_mapping(self, state: _FunctionalState) -> dict:
        """Retrieve the configured number of code candidates per requirement."""
        input_data = state["input_data"]
        fragments = input_data.code_fragments

        if not fragments:
            return {
                "candidates": {
                    req.requirement_id: []
                    for req in input_data.requirements
                }
            }

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

        similarity_matrix = util.cos_sim(
            requirement_vectors,
            code_vectors,
        )

        candidates = {}

        for index, requirement in enumerate(input_data.requirements):
            scores = similarity_matrix[index]
            top_indices = scores.argsort(descending=True)[
                :min(self.config.retrieval_top_k, len(fragments))
            ]

            candidates[requirement.requirement_id] = [
                CodeEvidence(
                    fragment_id=fragments[int(fragment_index)].fragment_id,
                    file_path=fragments[int(fragment_index)].file_path,
                    similarity=float(scores[int(fragment_index)]),
                )
                for fragment_index in top_indices
            ]

        return {"candidates": candidates}

    async def _verify(self, state: _FunctionalState) -> dict:
        """Use the LLM to assess each requirement against code evidence."""
        input_data = state["input_data"]
        candidates = state["candidates"]

        fragment_lookup = {
            fragment.fragment_id: fragment
            for fragment in input_data.code_fragments
        }

        results = []

        for requirement in input_data.requirements:
            evidence = candidates.get(requirement.requirement_id, [])

            if not evidence:
                results.append(
                    RequirementResult(
                        requirement_id=requirement.requirement_id,
                        description=requirement.description,
                        status="evidencia_insuficiente",
                        justification="No se proporcionaron fragmentos de código.",
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

        output = FunctionalAdequacyOutput(
            score=score,
            total_requirements=total,
            fulfilled_requirements=fulfilled,
            results=results,
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
