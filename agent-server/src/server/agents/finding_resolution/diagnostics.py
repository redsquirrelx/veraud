"""Content-limited diagnostics; never serialize response bodies or exception inputs."""

import hashlib
import json
import logging
import re

from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError


def safe_text(value, limit=500):
    text = str(value)
    text = re.sub(r"```.*?(?:```|$)", "<code omitted>", text, flags=re.DOTALL)
    text = re.sub(r"-----BEGIN .*?PRIVATE KEY-----.*?(?:-----END .*?PRIVATE KEY-----|$)", "<redacted>", text, flags=re.DOTALL)
    text = re.sub(r"(?i)\b(?:bearer\s+\S+|(?:sk-|AIza)[\w-]{12,})", "<redacted>", text)
    text = re.sub(r'''(?i)((?:api[_-]?key|password|secret|token|authorization)["']?\s*[:=]\s*)\S+''', r"\1<redacted>", text)
    text = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1<redacted>@", text)
    return text[:limit] + ("..." if len(text) > limit else "")


def safe_arguments(arguments):
    result = {}
    allowed = {"path", "file_path", "path_prefix", "name", "kind", "source_id", "target_id", "evidence_id", "project_id",
        "start_line", "end_line", "limit", "offset", "language", "status", "resolution", "case_sensitive"}
    for key, value in arguments.items():
        if key == "query" and isinstance(value, str):
            result[key] = {"characters": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()}
        elif key in allowed:
            result[key] = value if value is None or isinstance(value, (int, bool)) else safe_text(value)
        else:
            result["<other_argument>"] = "<omitted>"
    return result


def failure_text(text, diagnostics):
    if "response unavailable or invalid" in text:
        attempt = re.search(r"response_schema attempt (\d+)/", text)
        matching = [event for event in diagnostics if text.startswith(event["node"] + ":")
            and (attempt is None or event["attempt"] == int(attempt.group(1)))]
        detail = "; ".join(f"{item['field']}: {item['rule']}" for event in matching for item in event["issues"])
        text = text.replace("response unavailable or invalid", detail or "structured_response_validation_failed")
    return safe_text(text)


def error_details(error, schema, prefix=()):
    """Only known field names, rule codes and numeric constraints escape."""
    contract = schema.model_json_schema() if schema is not None else {}
    allowed = set(contract.get("properties", {}))
    for definition in contract.get("$defs", {}).values():
        allowed.update(definition.get("properties", {}))
    current, seen = error, set()
    while id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValidationError):
            issues = []
            for item in current.errors(include_input=False, include_context=True, include_url=False)[:8]:
                location = [str(part) if isinstance(part, int) or part in allowed else "<field>" for part in item["loc"]]
                constraints = {key: value for key, value in item.get("ctx", {}).items()
                    if key in {"ge", "gt", "le", "lt", "min_length", "max_length", "multiple_of"} and isinstance(value, (int, float))}
                issues.append({"field": ".".join([*map(str, prefix), *location]) or "response",
                    "rule": item["type"], "constraints": constraints})
            category = "malformed_response" if any(item["rule"] in {"json_invalid", "json_type"} for item in issues) else "pydantic_validation"
            return category, issues
        if isinstance(current, json.JSONDecodeError):
            return "malformed_response", [{"field": "response", "rule": "invalid_json",
                "line": current.lineno, "column": current.colno}]
        parsing_rules = {"Model output must be bounded JSON text.": "bounded_json_text_required",
            "Duplicate JSON keys are not permitted.": "duplicate_json_keys",
            "Nonstandard JSON numeric constants are not permitted.": "nonstandard_json_constant"}
        if isinstance(current, ValueError) and str(current) in parsing_rules:
            return "malformed_response", [{"field": "response", "rule": parsing_rules[str(current)]}]
        cause = current.__cause__ or current.__context__
        if cause is None:
            break
        current = cause
    if isinstance(error, OutputParserException):
        return "malformed_response", [{"field": "response", "rule": "output_parser_error"}]
    return "malformed_response", [{"field": "response", "rule": "structured_response_parse_failed"}]


class DiagnosticLogger(logging.LoggerAdapter):
    """Enrich only this execution's generic shared-runtime warning, not retry feedback."""

    def warning(self, msg, *args, **kwargs):
        if args and isinstance(args[0], str) and "response unavailable or invalid" in args[0]:
            event = self.extra.get("last_diagnostic", {})
            issues = event.get("issues", [])
            detail = "; ".join(f"{issue['field']}: {issue['rule']}" for issue in issues)
            replacement = f"{event.get('category', 'generation')}: {detail or 'structured_output_unavailable'}"
            args = (args[0].replace("response unavailable or invalid", replacement), *args[1:])
        super().warning(msg, *args, **kwargs)

    def process(self, msg, kwargs):
        return msg, kwargs  # Preserve explicit diagnostic metadata, not the private last-event cache.
