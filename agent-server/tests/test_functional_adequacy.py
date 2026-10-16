
import asyncio
import json
from unittest.mock import patch

import pytest

from server.agents.functional_adequacy.agent import FunctionalAdequacyAgent
from server.agents.functional_adequacy.config import FunctionalAdequacyConfig
from server.agents.functional_adequacy.schemas import FunctionalAdequacyInput


class FakeModel:
    pass


def build_agent():
    agent = FunctionalAdequacyAgent.__new__(FunctionalAdequacyAgent)
    agent.model = FakeModel()
    agent.config = FunctionalAdequacyConfig()
    agent._graph = agent._build_graph()
    return agent


def make_input(requirements, fragments):
    return FunctionalAdequacyInput.model_validate({
        "requirements": requirements,
        "code_fragments": fragments,
    })


def test_rejects_duplicate_requirement_ids():
    with pytest.raises(ValueError):
        make_input(
            [
                {"requirement_id": "REQ-001", "description": "Login"},
                {"requirement_id": "REQ-001", "description": "Logout"},
            ],
            [],
        )


def test_sbert_retrieves_expected_fragments():
    data = make_input(
        [
            {
                "requirement_id": "REQ-001",
                "description": "The system must authenticate users using a password.",
            },
            {
                "requirement_id": "REQ-002",
                "description": "The system must calculate the total price of a purchase.",
            },
        ],
        [
            {
                "fragment_id": "CODE-001",
                "file_path": "auth.py",
                "code": "def authenticate_user(username, password): return check_password(username, password)",
            },
            {
                "fragment_id": "CODE-002",
                "file_path": "sales.py",
                "code": "def calculate_total(items): return sum(item.price * item.quantity for item in items)",
            },
            {
                "fragment_id": "CODE-003",
                "file_path": "utils.py",
                "code": "def format_date(date): return date.strftime('%Y-%m-%d')",
            },
        ],
    )

    async def run_mapping():
        state = {"input_data": data}
        state.update(await FunctionalAdequacyAgent._prepare(None, state))
        return await FunctionalAdequacyAgent._code_mapping(build_agent(), state)

    result = asyncio.run(run_mapping())
    candidates = result["candidates"]

    assert candidates["REQ-001"][0].fragment_id == "CODE-001"
    assert candidates["REQ-002"][0].fragment_id == "CODE-002"


def test_full_execution_and_coverage():
    data = make_input(
        [
            {
                "requirement_id": "REQ-001",
                "description": "Authenticate users with passwords.",
            },
            {
                "requirement_id": "REQ-002",
                "description": "Calculate the total price considering quantities.",
            },
            {
                "requirement_id": "REQ-003",
                "description": "Recover forgotten passwords.",
            },
        ],
        [
            {
                "fragment_id": "CODE-001",
                "file_path": "auth.py",
                "code": "def authenticate_user(username, password): return check_password(username, password)",
            },
            {
                "fragment_id": "CODE-002",
                "file_path": "sales.py",
                "code": "def calculate_total(items): return sum(item.price for item in items)",
            },
        ],
    )

    async def fake_generate(model, prompt):
        if "Identificador: REQ-001" in prompt:
            status = "cumple"
        elif "Identificador: REQ-002" in prompt:
            status = "no_cumple"
        else:
            status = "evidencia_insuficiente"

        return json.dumps({
            "status": status,
            "justification": f"Evaluación simulada para {status}.",
        })

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=fake_generate,
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.total_requirements == 3
    assert output.fulfilled_requirements == 1
    assert output.score == 33.33
    assert [item.status for item in output.results] == [
        "cumple",
        "no_cumple",
        "evidencia_insuficiente",
    ]
    assert len(output.recommendations) == 2


def test_invalid_llm_response():
    data = make_input(
        [{"requirement_id": "REQ-001", "description": "Validate passwords."}],
        [{
            "fragment_id": "CODE-001",
            "file_path": "auth.py",
            "code": "def login(password): return True",
        }],
    )

    async def invalid_generate(model, prompt):
        return "Invalid response without JSON"

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=invalid_generate,
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.results[0].status == "evidencia_insuficiente"
    assert output.score == 0.0


def test_no_code_skips_sbert_and_llm():
    data = make_input(
        [{"requirement_id": "REQ-001", "description": "Allow login."}],
        [],
    )

    async def unexpected_generate(model, prompt):
        raise AssertionError("LLM should not execute")

    with (
        patch(
            "server.agents.functional_adequacy.agent.traced_generate",
            new=unexpected_generate,
        ),
        patch(
            "server.agents.functional_adequacy.agent._get_sbert_model",
            side_effect=AssertionError("SBERT should not execute"),
        ),
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.score == 0.0
    assert output.results[0].status == "evidencia_insuficiente"
    assert output.results[0].evidence == []


def test_llm_provider_failure():
    data = make_input(
        [{"requirement_id": "REQ-001", "description": "Validate passwords."}],
        [{
            "fragment_id": "CODE-001",
            "file_path": "auth.py",
            "code": "def validate_password(password): return len(password) >= 8",
        }],
    )

    async def failing_generate(model, prompt):
        raise ConnectionError("LLM provider unavailable")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=failing_generate,
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.results[0].status == "evidencia_insuficiente"
    assert output.score == 0.0
    assert output.fulfilled_requirements == 0
