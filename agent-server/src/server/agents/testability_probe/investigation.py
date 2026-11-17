"""Read-only investigation loop for the TestabilityProbeAgent.

Bounded LLM<->tool loop. Tools are strictly read-only and confined to the
disposable repository copy; results are truncated before they reach the model.
This phase gathers facts to author tests — it never audits, scores or fixes.
"""

import json

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from server.runtimes.verification.tools.code_search import CodeSearch
from server.runtimes.verification.tools.repo_reader import RepoReader

_MAX_TOOL_REPLY = 1500
_KEEP_RECENT_TURNS = 3
_COMPACT_TURN_SUMMARY_CHARS = 120

_MAX_LIST_ENTRIES = 80


def _rolling_messages(prompt: str, turns: list[list], keep: int = _KEEP_RECENT_TURNS) -> list:
    """Walk the message history with the last `keep` assistant/tool turns verbatim;
    older turns are collapsed into a single compact list to bound context growth."""
    def _turn_summary(turn: list) -> str:
        parts = []
        for message in turn[1:]:
            if isinstance(message, ToolMessage):
                parts.append(str(message.content)[:_COMPACT_TURN_SUMMARY_CHARS].replace("\n", " "))
        return "  - " + (" | ".join(parts) if parts else "(tool error)")

    if len(turns) <= keep:
        messages = [HumanMessage(content=prompt)]
        for turn in turns:
            messages.extend(turn)
        return messages
    older, recent = turns[:-keep], turns[-keep:]
    summary_lines = ["Earlier actions (each line summarizes one tool round):"] + [_turn_summary(turn) for turn in older]
    messages = [HumanMessage(content=prompt), HumanMessage(content="\n".join(summary_lines))]
    for turn in recent:
        messages.extend(turn)
    return messages


class ListFilesArgs(BaseModel):
    path: str = Field(default=".", description="Repository-relative directory to list (default: root).")


class ReadFileArgs(BaseModel):
    path: str = Field(description="Repository-relative file path.")
    max_lines: int = Field(default=160, ge=1, le=400, description="Maximum lines to return.")


class SearchTextArgs(BaseModel):
    query: str = Field(description="Literal text to search for.")
    path: str = Field(default=".", description="Repository-relative scope for the search.")


class SearchImportsArgs(BaseModel):
    module_prefix: str = Field(description="Dotted module prefix, e.g. 'httpx' or 'pkg.sub'.")
    path: str = Field(default=".", description="Repository-relative scope for the search.")


def _truncate(text: str, budget: int = _MAX_TOOL_REPLY) -> str:
    return text if len(text) <= budget else text[:budget] + "\n... [truncated]"


def build_tools(reader: RepoReader, searcher: CodeSearch, counters: dict) -> list[StructuredTool]:
    def _charge(tool: str) -> None:
        counters["tool_calls"] = counters.get("tool_calls", 0) + 1
        counters.setdefault("tools", []).append(tool)

    def list_files(path: str = ".") -> str:
        _charge("list_files")
        try:
            entries = reader.list_files(path, limit=_MAX_LIST_ENTRIES)
        except Exception as error:  # noqa: BLE001 - bounded tool; failures become observations
            return json.dumps({"error": str(error)}, ensure_ascii=False)
        return _truncate(json.dumps(entries, ensure_ascii=False))

    def read_file(path: str, max_lines: int = 160) -> str:
        _charge("read_file")
        try:
            record = reader.read_file(path)
        except Exception as error:  # noqa: BLE001 - bounded tool; failures become observations
            return json.dumps({"error": str(error)}, ensure_ascii=False)
        lines = record["content"].splitlines()[:max_lines]
        return _truncate(f"# {record['path']} (lines {record['start_line']}-{record['end_line']})\n" + "\n".join(lines))

    def search_text(query: str, path: str = ".") -> str:
        _charge("search_text")
        try:
            hits = searcher.search_text(query, path, limit=20)
        except Exception as error:  # noqa: BLE001 - bounded tool; failures become observations
            return json.dumps({"error": str(error)}, ensure_ascii=False)
        return _truncate(json.dumps(hits, ensure_ascii=False, default=str))

    def search_imports(module_prefix: str, path: str = ".") -> str:
        _charge("search_imports")
        try:
            hits = searcher.find_imports(module_prefix, path, limit=40)
        except Exception as error:  # noqa: BLE001 - bounded tool; failures become observations
            return json.dumps({"error": str(error)}, ensure_ascii=False)
        return _truncate(json.dumps(hits, ensure_ascii=False, default=str))

    return [
        StructuredTool.from_function(func=list_files, name="list_files", args_schema=ListFilesArgs,
                                     description="List repository files under a relative directory."),
        StructuredTool.from_function(func=read_file, name="read_file", args_schema=ReadFileArgs,
                                     description="Read a bounded excerpt of a repository-relative file."),
        StructuredTool.from_function(func=search_text, name="search_text", args_schema=SearchTextArgs,
                                     description="Search the repository for literal text."),
        StructuredTool.from_function(func=search_imports, name="search_imports", args_schema=SearchImportsArgs,
                                     description="List imports of a module prefix across the repository."),
    ]


async def run_investigation(chat_model, tools, prompt: str, *, max_iterations: int,
                            on_model_call=None, counters: dict | None = None) -> tuple[str, dict]:
    """Drive the LLM<->tool loop; returns (final_text, counters)."""

    counters = counters if counters is not None else {"tool_calls": 0, "tools": [], "model_calls": 0}
    model = chat_model.bind_tools(tools) if tools else chat_model
    final = ""
    turns: list[list] = []
    for _ in range(max_iterations):
        response = await model.ainvoke(_rolling_messages(prompt, turns))
        counters["model_calls"] += 1
        if on_model_call is not None:
            on_model_call(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        content = response.content
        text = content if isinstance(content, str) else str(content)
        if not tool_calls:
            final = text
            break
        turn = [response]
        for call in tool_calls:
            name = call.get("name") or ""
            args = call.get("args") or {}
            tool = next((item for item in tools if item.name == name), None)
            if tool is None:
                observation = json.dumps({"error": f"unknown tool {name!r}"})
            else:
                try:
                    observation = str(tool.func(**args))
                except TypeError as error:
                    observation = json.dumps({"error": f"bad arguments for {name}: {error}"})
                except Exception as error:  # noqa: BLE001 - bounded tool boundary
                    observation = json.dumps({"error": f"{name} failed: {error}"})
            turn.append(ToolMessage(content=observation, tool_call_id=call.get("id", "tool-call")))
        turns.append(turn)
    else:
        final = final or "Investigation ended without CONTEXT_READY (iteration cap reached)."
    return final, counters
