from google import genai

from ...config.logs import get_logger
from ...config.schemas import ModelCredentials, ModelSettings
from .base import Model  # Suponiendo que la clase base está en base.py

logger = get_logger("model.gemini")

class GeminiModel(Model):
    def __init__(self, settings: ModelSettings, credentials: ModelCredentials):
        super().__init__(settings, credentials)

        self.client = genai.Client(api_key=self.credentials.api_key)

    async def generate(self, message: str) -> str:
        logger.info(
            "generate: model=%r prompt_chars=%d", self.settings.name, len(message)
        )
        chat = self.client.aio.chats.create(model=self.settings.name)
        response = await chat.send_message(message)
        logger.info("generate done: response_chars=%d", len(response.text or ""))
        return response.text