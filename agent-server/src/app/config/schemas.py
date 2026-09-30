from pydantic import BaseModel

class ModelSettings(BaseModel):
    provider: str
    name: str
    temperature: float
    max_tokens: int

class AgentSettings(BaseModel):
    agent_id: str
    timeout_seconds: int
    
class ModelCredentials(BaseModel):
    api_key: str