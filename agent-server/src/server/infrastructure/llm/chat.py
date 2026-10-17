"""Native chat models for tool-using investigation and coordination graphs."""

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from ...config.schemas import ModelCredentials, ModelSettings

PROVIDERS = {"gemini": "google_genai", "google": "google_genai", "openai": "openai",
             "openrouter": "openai", "groq": "openai", "anthropic": "anthropic"}


def build_chat_model(settings: ModelSettings, credentials: ModelCredentials) -> BaseChatModel:
    provider = settings.provider.lower()
    if provider not in PROVIDERS:
        raise ValueError("Unsupported chat model provider.")
    options = {"api_key": credentials.api_key, "temperature": settings.temperature,
               "max_tokens": settings.max_tokens, "max_retries": 0}
    if provider == "openrouter":
        options["base_url"] = "https://openrouter.ai/api/v1"
    elif provider == "groq":
        options["base_url"] = "https://api.groq.com/openai/v1"
    return init_chat_model(settings.name, model_provider=PROVIDERS[provider], **options)
