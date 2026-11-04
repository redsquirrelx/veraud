"""Native chat models for tool-using investigation and coordination graphs."""

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from ...config.schemas import ModelCredentials, ModelSettings
from .quota import mark_quota_scope

PROVIDERS = {"gemini": "google_genai", "google": "google_genai", "openai": "openai",
             "openrouter": "openai", "groq": "openai", "anthropic": "anthropic"}


def prepare_chat_model(model, *, max_output_tokens, request_timeout_seconds):
    """Apply hard limits on a caller-owned copy using the provider's real fields.

    Gemini rejects call-time max_tokens. Model fields also survive native
    structured-output wrappers, which may not forward invocation kwargs.
    """
    output_limit = max_output_tokens
    options = {"max_tokens": output_limit}
    if isinstance(model, BaseChatModel):
        for field in ("max_output_tokens", "max_tokens"):
            if field in type(model).model_fields:
                # The execution configuration already resolved inheritance and
                # explicit overrides. Provider fields are its projection, not a
                # second independent ceiling (including provider SDK defaults).
                model = model.model_copy(update={field: output_limit})
                options = {}
                break
        for field in ("timeout", "request_timeout"):
            if field in type(model).model_fields:
                existing = getattr(model, field)
                if existing is None or isinstance(existing, (int, float)):
                    timeout = min(existing, request_timeout_seconds) if existing is not None else request_timeout_seconds
                    model = model.model_copy(update={field: timeout})
                break
    return model, options, output_limit


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
    return mark_quota_scope(init_chat_model(settings.name, model_provider=PROVIDERS[provider], **options), settings)
