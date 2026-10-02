from ..agents.base import BaseAgent
from ..config.logs import get_logger

logger = get_logger("agent-registry")

AgentClass = type[BaseAgent]


class UnknownAgentError(KeyError):
    pass


class AgentRegistry:
    """Maps agent_type to its agent class. It never creates agents,
    it only resolves which class to instantiate."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentClass] = {}

    def register(self, agent_type: str, agent_cls: AgentClass) -> None:
        logger.info("Registering agent %r", agent_type)
        self._agents[agent_type] = agent_cls

    def has(self, agent_type: str) -> bool:
        return agent_type in self._agents

    def list_agents(self) -> list[str]:
        return sorted(self._agents)

    def get(self, agent_type: str) -> AgentClass:
        try:
            return self._agents[agent_type]
        except KeyError:
            raise UnknownAgentError(f"Unknown agent: {agent_type!r}") from None
