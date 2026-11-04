from langchain_anthropic import ChatAnthropic

from ...config.schemas import ModelCredentials, ModelSettings
from .base import Model
from .quota import mark_quota_scope, quota_generate


class AnthropicModel(Model):
    def __init__(self, settings: ModelSettings, credentials: ModelCredentials):
        super().__init__(settings, credentials)
        self.llm = ChatAnthropic(
            model=settings.name,
            api_key=credentials.api_key,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=25,
            max_retries=0,
        )
        mark_quota_scope(self.llm, settings)

    async def generate(self, message: str):
        return await quota_generate(self, message, lambda: self.llm.ainvoke(message))
