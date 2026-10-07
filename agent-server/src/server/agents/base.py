from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..config.prompts import load_prompt, render_prompt
from ..config.schemas import AgentSettings
from .models.base import Model


class BaseAgent[AgentInput: BaseModel, AgentOutput: BaseModel](ABC):
    """Base class for audit agents.

    Lifecycle: built once then run once per input. Agents must be stateless.
    """

    agent_type: str
    input_schema: type[AgentInput]
    output_schema: type[AgentOutput]

    def __init__(self, settings: AgentSettings, model: Model):
        self.settings = settings
        self.model = model

    @classmethod
    def system_prompt(cls) -> str:
        """The agent's system prompt, loaded from prompts/<agent_type>/system.md.

        A classmethod, not an instance method: a prompt depends only on
        agent_type, so building an agent with its settings and model just to
        read a prompt would be pointless. It also lets tooling that has no
        model client, such as the dev runners, read prompts directly.
        """
        return load_prompt(cls.agent_type, "system")

    @classmethod
    def user_prompt(cls, **values: object) -> str:
        """Render prompts/<agent_type>/user.md with the given values."""
        return render_prompt(load_prompt(cls.agent_type, "user"), **values)

    @abstractmethod
    async def run(self, input_data: AgentInput) -> AgentOutput:
        """Run the agent graph and return the standard audit report."""
        raise NotImplementedError
