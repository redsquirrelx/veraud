from typing import Any

from langchain_openai import ChatOpenAI

from ...config.logs import get_logger
from ...config.schemas import ModelCredentials, ModelSettings
from .base import Model
from .quota import mark_quota_scope, quota_generate

logger = get_logger("model.groq")


class GroqModel(Model):
    """Groq's OpenAI-compatible chat endpoint, using the existing client."""

    def __init__(self, settings: ModelSettings, credentials: ModelCredentials):
        super().__init__(settings, credentials)
        self.llm = ChatOpenAI(
            model=settings.name,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            api_key=credentials.api_key,
            base_url="https://api.groq.com/openai/v1",
            max_retries=0,
        )
        mark_quota_scope(self.llm, settings)

    async def generate(self, message: str) -> Any:
        logger.info(
            "generate: model=%r prompt_chars=%d", self.settings.name, len(message)
        )
        response = await quota_generate(self, message, lambda: self.llm.ainvoke(message))
        logger.info("generate done")
        return response
