from google import genai
from google.genai import types

from ...config.logs import get_logger
from ...config.schemas import ModelCredentials, ModelSettings
from .base import Model

logger = get_logger("model.gemini")

class GeminiModel(Model):
    def __init__(self, settings: ModelSettings, credentials: ModelCredentials):
        super().__init__(settings, credentials)

        self.client = genai.Client(api_key=self.credentials.api_key)

    async def generate(self, message: str) -> str:
        logger.info(
            "generate: model=%r prompt_chars=%d", self.settings.name, len(message)
        )
        chat = self.client.aio.chats.create(model=self.settings.name, config=types.GenerateContentConfig(
            temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_tokens,
        ))
        response = await chat.send_message(message)
        logger.info("generate done: response_chars=%d", len(response.text or ""))
        return response.text
