from langchain_openai import ChatOpenAI

from ...config.logs import get_logger
from ...config.schemas import ModelCredentials, ModelSettings
from .base import Model

logger = get_logger("model.openrouter")

class OpenRouterModel(Model):
    def __init__(self, settings: ModelSettings, credentials: ModelCredentials):
        super().__init__(settings, credentials)

        self.llm = ChatOpenAI(
            model = settings.name,
            temperature = settings.temperature,
            max_tokens = settings.max_tokens,
            api_key = credentials.api_key,
            base_url = "https://openrouter.ai/api/v1",
        )

    async def generate(self, message: str) -> any:
        logger.info(
            "generate: model=%r prompt_chars=%d", self.settings.name, len(message)
        )
        llm = self.llm
        response = await llm.ainvoke(message)
        logger.info("generate done")
        return response
