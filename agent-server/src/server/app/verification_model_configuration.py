"""Explicit production configuration; local runners resolve their own dev entry."""

from pydantic import BaseModel, Field, SecretStr, model_validator

from config.agents.model import ModelCredentials, ModelSettings
from server.app.execution_config import ModelConfig


class VerificationModelConfiguration(BaseModel):
    model: ModelConfig
    api_key: SecretStr = Field(repr=False)

    @model_validator(mode="after")
    def explicit_access(self):
        if not (self.model.provider and self.model.provider.strip()
                and self.model.name and self.model.name.strip()
                and self.api_key.get_secret_value().strip()):
            raise ValueError("Verification Suite requires an explicit provider, model and credential.")
        if self.model.provider.lower() not in {"google", "gemini", "openai", "openrouter", "groq", "anthropic"}:
            raise ValueError("Unsupported verification model provider.")
        if self.model.temperature is not None and not 0 <= self.model.temperature <= 2:
            raise ValueError("Temperature must be between 0 and 2.")
        if self.model.max_tokens is not None and self.model.max_tokens < 1:
            raise ValueError("Maximum output tokens must be positive.")
        return self

    def resolve(self, config):
        return (ModelSettings(provider=self.model.provider, name=self.model.name,
                              temperature=self.model.temperature if self.model.temperature is not None else 0.2,
                              max_tokens=self.model.max_tokens if self.model.max_tokens is not None else config.max_output_tokens),
                ModelCredentials(api_key=self.api_key.get_secret_value()))
