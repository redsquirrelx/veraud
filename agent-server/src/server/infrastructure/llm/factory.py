"""Provider construction shared by direct and repository-backed execution."""

from config.agents.model import ModelCredentials, ModelSettings
from server.config.logs import get_logger
from server.infrastructure.llm.base import Model

logger = get_logger("model-factory")


class UnsupportedModelProviderError(ValueError):
    """Raised when settings select a provider without an adapter."""


def build_model(settings: ModelSettings, credentials: ModelCredentials) -> Model:
    provider = settings.provider.lower()
    logger.info("Building model provider=%r name=%r", provider, settings.name)
    if provider in ("gemini", "google"):
        from server.infrastructure.llm.gemini import GeminiModel

        return GeminiModel(settings=settings, credentials=credentials)
    if provider in ("openrouter", "openai"):
        from server.infrastructure.llm.openrouter import OpenRouterModel

        return OpenRouterModel(settings=settings, credentials=credentials)
    if provider == "groq":
        from server.infrastructure.llm.groq import GroqModel

        return GroqModel(settings=settings, credentials=credentials)
    if provider == "anthropic":
        from server.infrastructure.llm.anthropic import AnthropicModel

        return AnthropicModel(settings=settings, credentials=credentials)
    raise UnsupportedModelProviderError(f"Unsupported model provider: {settings.provider!r}")


def create_project_model(settings: ModelSettings, credentials: ModelCredentials) -> Model:
    """Construct a project-analysis model with the existing Gemini JSON limits."""
    if settings.provider.lower() not in ("google", "gemini"):
        return build_model(settings, credentials)

    from google.genai import types

    from server.infrastructure.llm.gemini import GeminiModel

    from .quota import quota_generate

    class ConfiguredGeminiModel(GeminiModel):
        async def generate(self, message):
            return await self.generate_with_output_limit(
                message, max_output_tokens=self.settings.max_tokens
            )

        async def generate_with_output_limit(self, message, *, max_output_tokens):
            output_limit = min(self.settings.max_tokens, max_output_tokens)
            return await quota_generate(
                self,
                message,
                lambda: self.client.aio.models.generate_content(
                    model=self.settings.name,
                    contents=str(message),
                    config=types.GenerateContentConfig(
                        temperature=self.settings.temperature,
                        max_output_tokens=output_limit,
                        response_mime_type="application/json",
                    ),
                ),
                max_output_tokens=output_limit,
            )

    return ConfiguredGeminiModel(settings, credentials)
