from pathlib import Path

import yaml

from .logs import get_logger
from .schemas import AgentSettings, ModelSettings

logger = get_logger("dev-agents-config")

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "dev-agents.yaml"

def load_dev_agents_config() -> dict[str, tuple[AgentSettings, ModelSettings]]:
    logger.info("Loading base agent config from %s", CONFIG_PATH)
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    agents = data.get("agents", {})
    logger.info("Loaded agents: %s", sorted(agents))

    return {
        agent_id: (AgentSettings(
            agent_id        = agent_id,
            timeout_seconds = agent_data.get("timeout_seconds", 60),
        ), ModelSettings(**agent_data["model"]))
        for agent_id, agent_data in agents.items()
    }
