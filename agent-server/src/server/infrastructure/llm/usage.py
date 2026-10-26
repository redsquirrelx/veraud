"""Observe model calls, including shared pacing and retry attempts."""

from typing import Any


def response_usage(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage_metadata", None) or {}
    metadata = getattr(response, "response_metadata", None) or {}
    if hasattr(usage, "prompt_token_count"):
        return {
            "input_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
        }
    if not usage:
        usage = metadata.get("token_usage", {})

    def count(*keys):
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return None

    return {
        "input_tokens": count("input_tokens", "prompt_tokens"),
        "output_tokens": count("output_tokens", "completion_tokens"),
    }


def extract_text(response: object) -> str:
    """Normalize whatever the model client returns into a string."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response

    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text

    return str(response)
