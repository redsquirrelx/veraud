"""Provider error classification and safe diagnostics shared across app and runtimes."""

import re

from server.infrastructure.llm.retry import http_status, retry_hints, retryable


def causes(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__

def provider_status(error):
    return next((status for cause in causes(error) if (status := http_status(cause)) is not None), None)

def transient(error):
    return any(retryable(cause) for cause in causes(error))

def retry_hint(error):
    """Prefer the original provider response over duplicated/translated wrapper hints."""
    for cause in reversed(list(causes(error))):
        hints = retry_hints(cause)
        if hints:
            return max(hints, key=lambda hint: hint.seconds)
    return None

def retry_delay(error):
    hint = retry_hint(error)
    return hint.seconds if hint is not None else 0

def quota_facts(error):
    """Only protocol quota identifiers/classifications, never descriptions or project IDs."""
    facts = []
    for cause in reversed(list(causes(error))):
        details = getattr(cause, "details", None)
        if not isinstance(details, dict):
            continue
        payload = details.get("error", details)
        if not isinstance(payload, dict):
            continue
        for detail in payload.get("details", []) or []:
            if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith("google.rpc.QuotaFailure"):
                continue
            for violation in detail.get("violations", []) or []:
                if not isinstance(violation, dict):
                    continue
                quota_id = violation.get("quotaId", "")
                metric = violation.get("quotaMetric", "")
                for name, value in (("quota_id", quota_id), ("quota_metric", metric)):
                    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_./:-]{1,200}", value):
                        facts.append(f"{name}={value}")
                kind = (str(quota_id) + " " + str(metric)).lower().replace("_", "")
                if "perday" in kind:
                    facts.append("quota_window=day")
                elif "perminute" in kind:
                    facts.append("quota_window=minute")
        if facts:
            break
    return list(dict.fromkeys(facts))

def response_payload(cause):
    """Read structured error bodies across SDK versions; callers allowlist output."""
    for name in ("details", "body", "response_json"):
        value = getattr(cause, name, None)
        if isinstance(value, dict) and value:
            return value.get("error", value)
    response = getattr(cause, "response", None)
    if callable(getattr(response, "json", None)):
        try:
            value = response.json()
        except (ValueError, TypeError, RuntimeError):
            return {}
        if isinstance(value, dict):
            return value.get("error", value)
    return {}

def request_facts(error):
    """Allowlisted request field names from structured Google BadRequest details."""
    aliases = {
        "response_schema": "response_schema", "responseSchema": "response_schema",
        "response_json_schema": "response_json_schema", "responseJsonSchema": "response_json_schema",
        "max_output_tokens": "max_output_tokens", "maxOutputTokens": "max_output_tokens",
        "temperature": "temperature", "tools": "tools", "contents": "contents",
        "thinking_config": "thinking_config", "thinkingConfig": "thinking_config",
        "tool_config": "tool_config", "toolConfig": "tool_config",
        "response_mime_type": "response_mime_type", "responseMimeType": "response_mime_type",
    }
    facts = []
    for cause in reversed(list(causes(error))):
        payload = response_payload(cause)
        if not isinstance(payload, dict) or not isinstance(payload.get("details", []), list):
            continue
        for detail in payload.get("details", [])[:8]:
            if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith("google.rpc.BadRequest"):
                continue
            violations = detail.get("fieldViolations", [])
            if not isinstance(violations, list):
                continue
            for violation in violations[:8]:
                field = violation.get("field") if isinstance(violation, dict) else None
                if isinstance(field, str):
                    parts = re.split(r"[.\[\]]", field)
                    # The first known request field is sufficient; nested schema
                    # property names and violation descriptions must never escape.
                    name = next((aliases[part] for part in parts if part in aliases), None)
                    if name:
                        facts.append(f"request_field={name}")
    return list(dict.fromkeys(facts))

def provider_diagnostic(error):
    """Emit only codes and fixed classifications, never an exception's raw message."""
    status = provider_status(error)
    facts = [f"http_status={status}"] if status is not None else []
    text = " ".join(str(cause).lower() for cause in causes(error))
    categories = {
        "schema_complexity": ("too many states", "schema is too complex", "schema has too many", "schema complexity"),
        "unsupported_schema": ("unsupported schema", "unsupported keyword", "unknown name", "not supported in the schema"),
        "invalid_argument": ("invalid_argument",),
        "quota_exhausted": ("resource_exhausted", "quota exceeded", "rate limit"),
        "authentication": ("unauthenticated", "api key not valid"),
        "model_prefilling": ("does not support model prefilling",),
        "unsupported_thinking": ("thinking is not supported", "thinking budget is not supported"),
    }
    facts.extend(name for name, patterns in categories.items() if any(p in text for p in patterns))
    hint = retry_hint(error)
    if hint is not None:
        facts.extend((f"retry_after_seconds={hint.seconds:g}", f"retry_after_source={hint.source}"))
    facts.extend(quota_facts(error))
    facts.extend(request_facts(error))
    if status == 400 and not any(fact.startswith("request_field=") for fact in facts):
        facts.append("request_field=not_reported")
    return "; " + ", ".join(facts) if facts else ""
