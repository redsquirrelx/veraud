"""Developer retrieval policy; common settings live in agent-server/config/agents/."""

from pydantic import Field

from config.agents import ConfigContract


class FunctionalAdequacyConfig(ConfigContract):
    embedding_model: str = Field(default="all-MiniLM-L6-v2", min_length=1)
    retrieval_top_k: int = Field(default=5, ge=1)
