"""Provider history filtering; authoritative graph messages remain untouched."""

import json

from langchain_core.messages import AIMessage, ToolMessage


def empty_ai_message(message):
    if not isinstance(message, AIMessage):
        return False
    if message.tool_calls or message.invalid_tool_calls or any(message.additional_kwargs.get(key) for key in ("tool_calls", "function_call")):
        return False
    content = message.content
    if isinstance(content, str):
        return not content.strip()
    for item in content:
        if isinstance(item, str):
            if item.strip():
                return False
        elif isinstance(item, dict) and item.get("type") == "text" and set(item) <= {"type", "text", "index"}:
            text = item.get("text")
            if text.strip() if isinstance(text, str) else text:
                return False
        else:
            return False  # Preserve reasoning, signatures and unknown content blocks.
    return True


def provider_history(messages):
    return [message for message in messages if not empty_ai_message(message)]


def compact_tool_history(messages, max_characters, pinned_evidence_ids=(), *, compact_metadata=False,
                         focus_search_results=False):
    """Replace old unreferenced tool payloads with re-reading pointers, preserving protocol.

    Never mutate graph history, truncate source, remove tool responses, or compact a
    cited excerpt. If pinned evidence itself is too large the normal hard cap applies.
    """
    history = provider_history(messages)
    size = sum(len(json.dumps(item.model_dump(), default=str)) for item in history)
    pinned = set(pinned_evidence_ids)
    latest_tools = [index for index, item in enumerate(history) if isinstance(item, ToolMessage)][-2:]
    for index, message in enumerate(history):
        if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
            continue
        try:
            payload = json.loads(message.content)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or payload.get("history_compacted"):
            continue
        evidence = payload.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(item, dict) for item in evidence):
            continue
        if focus_search_results and message.name == "search_repository_text":
            retained = [item for item in evidence if item.get("id") in pinned and item.get("kind") == "source"]
            data = payload.get("data", {})
            rows = data.get("items") if isinstance(data, dict) else None
            if retained and isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                selected = [row for row in rows if any(row.get("file_id") == ref.get("file_id")
                    and isinstance(row.get("line"), int)
                    and ref.get("start_line", 0) <= row["line"] <= ref.get("end_line", 0) for ref in retained)]
                if selected and len(selected) < len(rows):
                    focused = {**payload, "data": {**data, "items": selected,
                        "history_omitted_search_hits": len(rows) - len(selected)}, "evidence": retained}
                    content = json.dumps(focused, ensure_ascii=False)
                    size -= len(message.content) - len(content)
                    history[index] = message = message.model_copy(update={"content": content})
                    evidence = retained
        metadata_only = not any(item.get("kind") == "source" for item in evidence)
        if index in latest_tools and not (compact_metadata and metadata_only):
            continue
        if size <= max_characters and not (compact_metadata and metadata_only):
            continue
        if any(item.get("id") in pinned for item in evidence):
            continue
        content = json.dumps({"history_compacted": True,
            "notice": "Old uncited tool payload omitted for context. Read source again before using it in a conclusion.",
            "tool": message.name, "evidence": evidence}, ensure_ascii=False)
        if len(content) < len(message.content):
            history[index] = message.model_copy(update={"content": content})
            size -= len(message.content) - len(content)
    return history
