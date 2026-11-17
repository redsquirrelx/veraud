"""LangChain chat construction for tool-capable verification clients."""

from langchain.chat_models import init_chat_model

from config.agents.model import ModelCredentials, ModelSettings


def build_chat_model(settings: ModelSettings, credentials: ModelCredentials):
    provider = settings.provider.lower()
    kwargs = {"api_key": credentials.api_key, "temperature": settings.temperature,
              "max_tokens": settings.max_tokens, "max_retries": 0}
    if provider in {"google", "gemini"}:
        provider = "google_genai"
    elif provider in {"openrouter", "groq"}:
        kwargs["base_url"] = ("https://openrouter.ai/api/v1" if provider == "openrouter"
                              else "https://api.groq.com/openai/v1")
        provider = "openai"
    elif provider not in {"openai", "anthropic"}:
        raise ValueError("Unsupported verification model provider")
    return init_chat_model(settings.name, model_provider=provider, **kwargs)
