from langchain_openai import ChatOpenAI

from ...config.logs import get_logger
from ...config.schemas import ModelCredentials, ModelSettings
from .base import Model
from .quota import mark_quota_scope, quota_generate

logger = get_logger("model.openrouter")

class OpenRouterModel(Model):
    def __init__(self, settings: ModelSettings, credentials: ModelCredentials):
        super().__init__(settings, credentials)

        self.llm = ChatOpenAI(
            model = settings.name,
            temperature = settings.temperature,
            max_tokens = settings.max_tokens,
            api_key = credentials.api_key,
            base_url = "https://api.openai.com/v1" if settings.provider.lower() == "openai" else "https://openrouter.ai/api/v1",
            timeout = 25,
            max_retries = 0,
        )
        mark_quota_scope(self.llm, settings)

    async def generate(self, message: str) -> any:
        logger.info(
            "generate: model=%r prompt_chars=%d", self.settings.name, len(message)
        )
        llm = self.llm
        response = await quota_generate(self, message, lambda: llm.ainvoke(message))
        logger.info("generate done")
        return response
