"""DEV-ONLY test flow (agent-server only).

Runs DummyAgent with a sample code snippet,
executes its LangGraph nodes and prints the standard audit JSON.

Usage (from agent-server):
    uv run python -m server.test_agent
"""

import asyncio

from pydantic import ValidationError

from server.agents.dummy.agent import DummyAgent
from server.agents.dummy.schemas import DummyInput
from server.agents.models.gemini import GeminiModel
from server.config.dev_agents_config import load_dev_agents_config
from server.config.schemas import ModelCredentials

SAMPLE_CODE = """def calculate_total(items):
    total = 0
    for i in items:
        total += i  # TODO: validate types
    print(total)
    try:
        return total
    except:
        return 0
"""


def _build_model(model_settings: object) -> GeminiModel:
    try:
        from server.config.settings import get_server_settings
        api_key = get_server_settings().llm_api_key
    except ValidationError:
        # No .env / no key: the agent uses its deterministic local fallback.
        api_key = "dev-dummy-key"
    return GeminiModel(
        settings=model_settings,
        credentials=ModelCredentials(api_key=api_key),
    )


def main() -> None:
    agents = load_dev_agents_config()
    agent_settings, model_settings = agents["dummy"]

    model = _build_model(model_settings)
    agent = DummyAgent(settings=agent_settings, model=model)

    result = asyncio.run(agent.run(DummyInput(code=SAMPLE_CODE)))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
