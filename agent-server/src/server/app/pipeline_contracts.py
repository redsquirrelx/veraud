"""Data contract for a named pipeline composition."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


def bind_legacy_blackboard(agents, _ctx, blackboard, _audit_service) -> None:
    """Preserve the existing context injection contract for custom pipelines."""
    if blackboard is not None:
        for participant in agents.values():
            participant.blackboard = blackboard


def bind_no_context(_agents, _ctx, _blackboard, _audit_service) -> None:
    """A pipeline whose run function consumes request-scoped services explicitly."""


@dataclass
class PipelineDefinition:
    name: str
    stages: list[str]
    parse_input: Callable[[dict], Any]
    build_agents: Callable[..., Any] = field(repr=False)
    adapt_hooks: Callable[[Any], Any] = field(repr=False)
    create_pipeline: Callable[[dict[str, Any], Any, dict[str, Any]], Any] = field(repr=False)
    run_pipeline: Callable[..., Any] = field(repr=False)
    agent_types: dict[str, str] | None = None
    resolve_stages: Callable[[Any], list[str]] | None = None
    close_resources: Callable[[dict[str, Any]], Awaitable[None]] | None = field(
        default=None, repr=False
    )
    bind_context: Callable[..., None] = field(
        default=bind_legacy_blackboard, repr=False
    )
    requires_agent_execution_service: bool | None = None

    def agent_type_for(self, stage: str) -> str:
        return (self.agent_types or {}).get(stage, stage)
