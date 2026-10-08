"""Reading what the model sends back.

The model is never trusted to honour the schema. Every answer passes through
here: unusable text becomes a ValueError, and off-vocabulary values are
demoted to the conservative option rather than rejected, because an answer
outside the vocabulary still tells the reader the model was unsure.
"""

import json

from .schemas import ProjectDescription

KINDS = frozenset({
    "cli", "library", "web_service", "desktop_app",
    "data_pipeline", "script", "unknown",
})

CONFIDENCES = frozenset({"low", "medium", "high"})


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model response."""
    if not text or not text.strip():
        raise ValueError("empty response")

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")

    parsed = json.loads(text[start:end + 1])

    if not isinstance(parsed, dict):
        raise TypeError("response was not a JSON object")

    return parsed


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


def read_kind(parsed: dict) -> str:
    """The project category, or `unknown` when off-vocabulary."""
    candidate = str(parsed.get("kind") or "").strip().lower()
    return candidate if candidate in KINDS else "unknown"


def read_confidence(parsed: dict, kind: str) -> str:
    """The stated confidence, forced to `low` when the kind is unknown.

    Claiming high confidence about a project you could not classify is the one
    combination this refuses to pass through.
    """
    if kind == "unknown":
        return "low"

    candidate = str(parsed.get("confidence") or "").strip().lower()
    return candidate if candidate in CONFIDENCES else "low"


def read_paths(parsed: dict, key: str, known: set[str]) -> list[str]:
    """Paths the model named, keeping only the ones that exist in the repository.

    Models invent paths. An invented path would send the next node to read a
    file that is not there, so anything unrecognised is dropped here.
    """
    chosen: list[str] = []

    for value in _as_list(parsed.get(key)):
        path = str(value).strip()
        if path in known and path not in chosen:
            chosen.append(path)

    return chosen


def read_text(parsed: dict, key: str) -> str:
    value = parsed.get(key)
    return str(value).strip() if isinstance(value, str) else ""


def build_description(
    parsed: dict,
    *,
    files_read: int,
    read_rounds: int,
    hypothesis_confirmed: bool,
    known_files: set[str],
) -> ProjectDescription:
    """Shape the synthesis answer into a valid description."""
    kind = read_kind(parsed)
    summary = read_text(parsed, "summary") or "The model returned no summary."

    return ProjectDescription(
        kind=kind,
        summary=summary,
        primary_language=read_text(parsed, "primary_language") or "unknown",
        files_read=files_read,
        read_rounds=read_rounds,
        hypothesis_confirmed=hypothesis_confirmed,
        confidence=read_confidence(parsed, kind),
        entrypoints=read_paths(parsed, "entrypoints", known_files),
        key_components=read_paths(parsed, "key_components", known_files),
    )


def unavailable(reason: str, files_read: int = 0) -> ProjectDescription:
    """What the agent returns when it could not describe the repository.

    Deliberately not a raising error: a description that says nothing was
    learned is more useful downstream than a failed request, because the next
    agent can still see which repository it was looking at.
    """
    return ProjectDescription(
        kind="unknown",
        summary=reason,
        primary_language="unknown",
        confidence="low",
        files_read=files_read,
    )


def _as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value]
    return []