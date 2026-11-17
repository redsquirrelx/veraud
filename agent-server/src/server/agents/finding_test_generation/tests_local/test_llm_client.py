"""LLM adapter surface: rule selection only.

The model is never used to generate or repair test code; the single model
call in the pipeline is ``select_rule``.
"""

import asyncio
import json
from pathlib import Path

from server.agents.finding_test_generation.input_adapter import load_audit_document
from server.agents.finding_test_generation.llm_client import ScriptedLLMClient
from server.agents.finding_test_generation.planning import plan_verifications

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"


def test_planning_is_deterministic():
    document, _ = load_audit_document(FIXTURE)
    first, first_limits = plan_verifications(document)
    second, second_limits = plan_verifications(document)
    assert [item.verification_id for item in first] == [item.verification_id for item in second]
    assert first_limits == second_limits


def test_scripted_client_defaults_to_low_confidence():
    client = ScriptedLLMClient()
    answer = asyncio.run(client.select_rule("prompt"))
    payload = json.loads(answer)
    assert payload["confidence"] == "low"
    assert client.calls == [{"node": "select_rule"}]


def test_scripted_client_returns_fifo_selections():
    client = ScriptedLLMClient(selections=['{"rule_id": "layer_import", "parameters": {}, "confidence": "high", "reason": "x"}'])
    answer = asyncio.run(client.select_rule("prompt"))
    assert json.loads(answer)["rule_id"] == "layer_import"
    # Queue exhausted: deterministic fall-back answer
    fallback = json.loads(asyncio.run(client.select_rule("prompt")))
    assert fallback["confidence"] == "low"
