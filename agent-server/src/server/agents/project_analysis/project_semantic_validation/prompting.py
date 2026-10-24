"""Bounded batches retain claim text and reduce tool metadata before source."""

import json
from pathlib import Path

from ....runtimes.repository.telemetry import measure_json, measured_prompt
from ....runtimes.repository.token_budget import input_ratio
from ....runtimes.repository.tools import tool_signatures
from ....runtimes.repository.working_context import WorkingContext
from .context import target_was_inspected
from .schemas import ValidationTurn

ALLOWED_TOOLS = {
    "get_source_excerpt",
    "list_relationships",
    "find_symbols",
    "list_files",
    "search_repository_text",
}
PROMPTS = Path(__file__).parent / "prompts"


def prepare_prompt(state, context):
    budget = context.tools.context.input.budget
    active = [
        target for target in state["selected"] if target.id not in state["findings"]
    ][: context.limits.batch_size]
    working = WorkingContext({}, state["responses"])
    cap = min(
        context.limits.max_prompt_characters,
        int(budget.max_input_tokens_per_call / input_ratio(context.generate)) - 128,
    )
    if context.soft_token_budgets:
        cap = context.limits.max_prompt_characters
    paths = {
        source.id: source.path for source in context.tools.accessible_snapshot.files
    }
    ledger = [
        {
            "id": record.id,
            "path": paths[record.file_id],
            "start_line": record.start_line,
            "end_line": record.end_line,
        }
        for record in context.tools.retrieved_evidence
        if record.kind == "source"
    ]
    remaining_tools = (
        min(context.limits.max_tool_calls, budget.max_tool_calls)
        - context.tools.budget_usage.tool_calls
    )
    full_schema = ValidationTurn.model_json_schema()
    source_schema = {
        "type": "object",
        "properties": {
            "tool_calls": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {"$ref": "#/$defs/RepositoryToolCall"},
            }
        },
        "required": ["tool_calls"],
        "additionalProperties": False,
        "$defs": {"RepositoryToolCall": full_schema["$defs"]["RepositoryToolCall"]},
    }
    while True:
        unread = {
            (hint.file_id, hint.start_line, hint.end_line): hint.model_dump(mode="json")
            for target in active
            if target.source_hints
            and not target_was_inspected(target, context.tools.retrieved_evidence)
            for hint in target.source_hints
        }
        need_source = bool(unread) or (not ledger and bool(paths))
        schema = source_schema if need_source and remaining_tools else full_schema
        data = {
            "report_hash": state["report_hash"],
            "active_targets": [target.model_dump(mode="json") for target in active],
            "tool_results": working.responses,
            "omitted_tool_results": working.omitted_results,
            "source_evidence_ledger": ledger,
            "uninspected_source_hints": list(unread.values()),
            "required_action": "Use tool_calls to read uninspected_source_hints before closing this batch."
            if need_source and remaining_tools
            else "Inspect missing context OR return findings for this batch.",
            "candidate_paths": sorted(paths.values())[:12] if not ledger else [],
            "validation_errors": state["errors"],
            "remaining_model_calls": min(
                context.limits.max_model_calls, budget.max_model_calls
            )
            - state["calls"],
            "remaining_tool_calls": min(
                context.limits.max_tool_calls, budget.max_tool_calls
            )
            - context.tools.budget_usage.tool_calls,
        }
        text, sizes = measure_json(
            data, fields={"tool_results": "history", "validation_errors": "feedback"}
        )
        prompt = measured_prompt(
            [
                ((PROMPTS / "system.md").read_text(encoding="utf-8"), "instructions"),
                (
                    (PROMPTS / "investigation.md").read_text(encoding="utf-8"),
                    "instructions",
                ),
                (
                    "\nOUTPUT_SCHEMA\n" + json.dumps(schema, separators=(",", ":")),
                    "contracts",
                ),
                (
                    "\nTOOLS\n"
                    + json.dumps(
                        {
                            key: value
                            for key, value in tool_signatures().items()
                            if key in ALLOWED_TOOLS
                        },
                        separators=(",", ":"),
                    ),
                    "contracts",
                ),
                ("\nVALIDATION_DATA\n", "framing"),
                (text, sizes),
            ],
            stage="investigation",
            objective_id=context.objective_id,
            correction=bool(state["errors"]),
        )
        if len(prompt) <= cap:
            return prompt, {target.id for target in active}
        if not working.reduce():
            if len(active) > 1:
                active.pop()
            else:
                return prompt, {target.id for target in active}
