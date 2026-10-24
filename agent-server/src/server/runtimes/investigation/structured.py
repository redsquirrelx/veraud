"""Structured response parsing and diagnostics that never echo provider payloads."""

import json

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticCustomError

from ..repository.model_runtime import extract_text
from ..repository.responses import parse_json_value


def parse_structured(response, schema, native, prepare=None):
    """Optional `prepare` normalizes the parsed payload before canonical validation.

    The provider schema is deliberately leaner than the canonical contract, so it can
    admit a collection the contract rejects. A specialization uses this hook to convert
    such payloads into an actionable state instead of an unactionable parse error.
    """
    if native:
        if response.get("parsing_error") is not None:
            raise response["parsing_error"]
        parsed = response.get("parsed")
        if isinstance(parsed, BaseModel):
            parsed = parsed.model_dump()
        return schema.model_validate(prepare(parsed) if prepare else parsed)
    text = extract_text(response).strip()
    # Some fallback models wrap otherwise valid JSON in a Markdown code fence.
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    value = parse_json_value(text, 160_000)
    return schema.model_validate(prepare(value) if prepare else value)


def safe_diagnostic(error, schema=None):
    """Only known schema field names, numeric positions, and error codes escape.

    In particular, ValidationError input/ctx/msg and OutputParserException text can
    contain entire source excerpts, credentials or arbitrary model-generated keys.
    """
    allowed_fields = set()
    # Known provider configuration fields are safe, useful request diagnostics.
    allowed_fields.update({"max_tokens", "max_output_tokens", "temperature", "response_json_schema"})
    if schema:
        contract = schema.model_json_schema()
        allowed_fields.update(contract.get("properties", {}))
        for definition in contract.get("$defs", {}).values():
            allowed_fields.update(definition.get("properties", {}))
    current = error
    seen = set()
    for _ in range(8):
        if id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, PydanticCustomError):
            feedback = getattr(schema, "validation_feedback", {})
            if current.type in feedback:
                return f"ValidationError (response: {current.type})"
        if isinstance(current, ValidationError):
            details = []
            for item in current.errors(include_input=False, include_context=False, include_url=False)[:6]:
                location = ".".join(
                    str(part) if isinstance(part, int) or part in allowed_fields else "<field>"
                    for part in item["loc"]
                ) or "response"
                details.append(f"{location}: {item['type']}")
            return f"ValidationError ({'; '.join(details)})"
        if isinstance(current, json.JSONDecodeError):
            return f"JSONDecodeError (line {current.lineno}, column {current.colno})"
        cause = current.__cause__ or current.__context__
        if cause is None:
            break
        current = cause
    return f"{type(error).__name__} (response unavailable or invalid)"


def correction_feedback(error, schema):
    """Only trusted contract-defined messages are sent back, never provider input/msg/ctx."""
    feedback = getattr(schema, "validation_feedback", {})
    current, seen = error, set()
    for _ in range(8):
        if id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, PydanticCustomError):
            codes = [current.type]
        elif isinstance(current, ValidationError):
            codes = [item["type"] for item in current.errors(include_input=False, include_context=False, include_url=False)[:6]]
        else:
            codes = []
        hints = [feedback[code] for code in dict.fromkeys(codes) if code in feedback]
        if hints:
            return " ".join(hints)
        current = current.__cause__ or current.__context__
        if current is None:
            break
    return "Follow every field, type, enum and constraint in the response schema; do not omit required fields."


def finish_diagnostic(response):
    metadata = getattr(response, "response_metadata", {}) or {}
    reason = metadata.get("finish_reason")
    if reason in ("MAX_TOKENS", "length"):
        return "; output_token_limit_reached"
    if reason in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "content_filter"):
        return "; provider_content_filter"
    return ""
