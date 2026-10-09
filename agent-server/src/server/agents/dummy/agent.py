from __future__ import annotations

import json
import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ...config.logs import get_logger
from ...config.tracing import traced_generate
from ..base import BaseAgent
from .schemas import DummyInput, DummyOutput, Finding

logger = get_logger("dummy-agent")


class _DummyState(TypedDict, total=False):
    code: str
    attribute: str
    raw_analysis: str
    result: dict


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_text(response: object) -> str:
    """Normalize whatever Gemini/OpenRouter/LangChain returns into str."""
    if response is None:
        return ""
    
    if isinstance(response, str):
        return response
    
    content = getattr(response, "content", None)

    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    
    text = getattr(response, "text", None)

    if isinstance(text, str):
        return text
    
    return str(response)


class DummyAgent(BaseAgent[DummyInput, DummyOutput]):
    agent_type = "dummy"
    input_schema = DummyInput
    output_schema = DummyOutput

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(_DummyState)
        graph.add_node("prepare_context", self._prepare_node)
        graph.add_node("analyze", self._analyze_node)
        graph.add_node("format_report", self._format_node)

        graph.set_entry_point("prepare_context")
        graph.add_edge("prepare_context", "analyze")
        graph.add_edge("analyze", "format_report")
        graph.add_edge("format_report", END)
        return graph.compile()

    async def _prepare_node(self, state: _DummyState) -> dict:
        code = (state.get("code") or "").strip()
        attribute = state.get("attribute") or "maintainability"
        logger.info("prepare_context: code_chars=%d attribute=%r", len(code), attribute)
        return {"code": code, "attribute": attribute}

    async def _analyze_node(self, state: _DummyState) -> dict:
        code = state.get("code", "")
        attribute = state.get("attribute", "maintainability")

        if not code:
            return {"raw_analysis": "", "result": {
                "evaluated_attribute": attribute,
                "score": 0.0,
                "findings": [{"title": "No input code",
                               "description": "No snippet received for audit.",
                               "severity": "high"}],
                "recommendations": ["Send a code snippet or test repo path."],
            }}

        prompt = (
            f"{self.system_prompt()}\n\n{self.user_prompt(attribute=attribute, code=code)}"
        )

        try:
            logger.info("analyze: calling model (prompt_chars=%d)", len(prompt))
            response = await traced_generate(self.model, prompt)
            text = _extract_text(response)
            match = _JSON_RE.search(text)

            if not match:
                raise ValueError("Model did not return JSON")

            parsed = json.loads(match.group(0))
            logger.info("analyze: model returned valid JSON")
            return {"raw_analysis": text, "result": parsed}
        except Exception as error:  # noqa: BLE001 - providers raise varied
            # errors (API, network, retries); any failure maps to error result.
            logger.warning("analyze: LLM unavailable (%s), using error result", error)
            return {"raw_analysis": "", "result": "unable to analyze: no llm service available" }

    async def _format_node(self, state: _DummyState) -> dict:
        data = state.get("result") or {}

        if not isinstance(data, dict):
            data = {
                "evaluated_attribute": state.get("attribute") or "maintainability",
                "score": 0.0,
                "findings": [{"title": "Analysis unavailable",
                               "description": str(data),
                               "severity": "high"}],
                "recommendations": ["Retry with the LLM service available."],
            }

        findings = [
            item if isinstance(item, dict) else {}
            for item in data.get("findings", [])
            if isinstance(item, dict)
        ]

        score = data.get("score", 0.0)

        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        
        result = {
            "evaluated_attribute": str(data.get("evaluated_attribute")
                                       or state.get("attribute")
                                       or "maintainability"),
            "score": max(0.0, min(100.0, score)),
            "findings": findings,
            "recommendations": [str(item) for item in data.get("recommendations", [])],
        }

        logger.info(
            "format_report: score=%.1f findings=%d",
            result["score"], len(findings),
        )
        return {"result": result}

    async def run(self, input_data: DummyInput) -> DummyOutput:
        logger.info(
            "run: attribute=%r code_chars=%d",
            input_data.evaluated_attribute, len(input_data.code),
        )
        final = await self._graph.ainvoke({
            "code": input_data.code,
            "attribute": input_data.evaluated_attribute,
        })

        data = final.get("result", {})

        findings = [Finding(**item) if isinstance(item, dict) else item
                    for item in data.get("findings", [])]
        
        output = DummyOutput(
            evaluated_attribute=data.get("evaluated_attribute", input_data.evaluated_attribute),
            score=data.get("score", 0.0),
            findings=findings,
            recommendations=data.get("recommendations", []),
        )
        logger.info(
            "run done: score=%.1f findings=%d",
            output.score, len(output.findings),
        )
        return output
