from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..config.schemas import AgentSettings
from .models.base import Model


class BaseAgent[AgentInput: BaseModel, AgentOutput: BaseModel](ABC):
    """Base class for audit agents.

    Lifecycle: built once then run once per input. Agents must be stateless.
    """

    agent_type: str
    system_prompt: str
    input_schema: type[AgentInput]
    output_schema: type[AgentOutput]

    def __init__(self, settings: AgentSettings, model: Model):
        self.settings = settings
        self.model = model

    @abstractmethod
    async def run(self, input_data: AgentInput) -> AgentOutput:
        """Run the agent graph and return the standard audit report."""
        raise NotImplementedError
