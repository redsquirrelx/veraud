"""Full-output fingerprints captured from sprint2 commit ad4e0b3.

The pre-merge agent and the integrated agent were run against identical inputs,
rankings and provider responses. These expectations retain that exact behavior
without making tests depend on Git history or external providers/models.
"""

import asyncio
import hashlib
import json
from unittest.mock import patch

import pytest

from server.agents.functional_adequacy import agent as implementation
from server.agents.functional_adequacy.config import FunctionalAdequacyConfig
from server.agents.functional_adequacy.schemas import FunctionalAdequacyInput
from server.config.schemas import AgentSettings

REQUIREMENTS_INPUT = {
    "requirements": [{"requirement_id": "REQ-001", "description": "List items."}],
    "code_fragments": [{"fragment_id": "1", "file_path": "app.py:1-2", "code": "def list_items():\n    return []"}],
}
CASES = {
    "exploratory": ({"code_fragments": [
        {"fragment_id": "1", "file_path": "app.py:1-3", "code": '@app.get("/items")\ndef list_items():\n    return []'},
        {"fragment_id": "2", "file_path": "service.py:1-2", "code": "def pending():\n    pass"},
    ]}, "a3ead0e30f8868727f5ed202b87a38ad8782a3e91863aec1b73511668eefb664"),
    "empty": ({}, "3359c67813d605986c093deb2bf4592c0dbf6668c53205be81b469597205aa40"),
    "requirements": (REQUIREMENTS_INPUT, "6ee90b4c7de2d82c82a294607835a869824d095e4cb9064606e8ef8a7f7c25dd"),
    "missing_dependency": (REQUIREMENTS_INPUT, "db711edb1496b3d05249dd2fdb8603f6af60c1f8a8ede169419bb02c45b67af7"),
    "invalid_llm": (REQUIREMENTS_INPUT, "d340805963280801c2b166e9ef90f07fdecdf2d9a8094e91959e49bfcf07054a"),
}


class Scores(list):
    def argsort(self, descending=False):
        return sorted(range(len(self)), key=self.__getitem__, reverse=descending)


class Embeddings:
    def encode(self, values, **kwargs):
        return values


@pytest.mark.parametrize("case", CASES)
def test_full_agent_output_matches_pre_merge_branch(case):
    payload, expected = CASES[case]
    agent = implementation.FunctionalAdequacyAgent(
        AgentSettings(agent_id="functional_adequacy", timeout_seconds=120), model=None,
        config=FunctionalAdequacyConfig())

    async def generate(*args, **kwargs):
        return "not-json" if case == "invalid_llm" else '{"status":"cumple","justification":"Lists items."}'

    with (
        patch.object(implementation, "_get_sbert_model", return_value=Embeddings(),
            side_effect=implementation.SemanticRetrievalUnavailableError(implementation.SBERT_DEPENDENCY_ERROR)
            if case == "missing_dependency" else None),
        patch.object(implementation, "_cosine_similarity", return_value=[Scores([0.9])]),
        patch.object(implementation, "traced_generate", new=generate),
    ):
        result = asyncio.run(agent.run(FunctionalAdequacyInput.model_validate(payload))).model_dump(mode="json")
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    assert hashlib.sha256(serialized).hexdigest() == expected
