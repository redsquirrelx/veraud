"""Compatibility exports; agent settings are owned by agent-server/config/agents/."""

from config.agents.model import AgentSettings, ModelCredentials, ModelSettings

__all__ = ["AgentSettings", "ModelCredentials", "ModelSettings"]
