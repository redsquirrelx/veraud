from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel

from config.agents.model import AgentSettings
from server.config.prompts import load_prompt, render_prompt
from server.infrastructure.llm.base import Model

if TYPE_CHECKING:
    from server.blackboard.interface import Blackboard


class BaseAgent[AgentInput: BaseModel, AgentOutput: BaseModel](ABC):
    """Base class for audit agents.

    Lifecycle: built once then run once per input. Agents must be stateless.
    """

    agent_type: str
    input_schema: type[AgentInput]
    output_schema: type[AgentOutput]
    prompt_directory: ClassVar[Path | None] = None

    def __init__(self, settings: AgentSettings, model: Model, *, blackboard: "Blackboard | None" = None):
        self.settings = settings
        self.model = model
        self.blackboard = blackboard

    @classmethod
    def system_prompt(cls) -> str:
        """The agent's system prompt, loaded from its package-local prompt directory.

        A classmethod, not an instance method: a prompt depends only on
        agent_type, so building an agent with its settings and model just to
        read a prompt would be pointless. It also lets tooling that has no
        model client, such as the dev runners, read prompts directly.
        """
        return load_prompt(cls.agent_type, "system", directory=cls.prompt_directory)

    @classmethod
    def user_prompt(cls, **values: object) -> str:
        """Render prompts/<agent_type>/user.md with the given values."""
        return render_prompt(load_prompt(cls.agent_type, "user", directory=cls.prompt_directory), **values)

    @abstractmethod
    async def run(self, input_data: AgentInput) -> AgentOutput:
        """Run the agent graph and return the standard audit report."""
        raise NotImplementedError
