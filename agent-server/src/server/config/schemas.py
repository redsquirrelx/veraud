from pydantic import BaseModel


class ModelSettings(BaseModel):
    """Resolved model settings used to build a model client.

    Complete on purpose, unlike the partial ModelConfig from the api.
    Produced by merging ExecutionConfig over dev_agents_config.
    """

    provider: str
    name: str
    temperature: float
    max_tokens: int


class AgentSettings(BaseModel):
    agent_id: str
    timeout_seconds: int


class ModelCredentials(BaseModel):
    api_key: str
