"""Compact orientation prompts with a source-first context fitting policy."""

import json

from server.project_analysis.project_orientation.context import prompt_template
from server.project_analysis.project_orientation.schemas import OrientationTurn
from server.runtimes.repository.telemetry import measure_json, measured_prompt
from server.runtimes.repository.token_budget import input_ratio
from server.runtimes.repository.tools import tool_signatures
from server.runtimes.repository.working_context import WorkingContext

ALLOWED_TOOLS = {
    "list_files",
    "find_symbols",
    "get_source_excerpt",
    "list_relationships",
    "search_repository_text",
}


def prepare_prompt(state, context, max_calls):
    budget = context.tools.context.input.budget
    working = WorkingContext(state["representation"], state["responses"])
    evidence = [
        {
            "id": record.id,
            "file_id": record.file_id,
            "start_line": record.start_line,
            "end_line": record.end_line,
        }
        for record in context.tools.retrieved_evidence
        if record.kind == "source"
    ]
    cap = min(
        context.limits.max_prompt_characters,
        int(budget.max_input_tokens_per_call / input_ratio(context.generate)) - 128,
    )
    fit_cap = cap if working.responses else cap - min(3000, cap // 4)
    while True:
        data = {
            "representation": working.representation,
            "tool_results": working.responses,
            "omitted_tool_results": working.omitted_results,
            "source_evidence_ledger": evidence,
            "query_ledger": [
                item["signature"][:180] for item in state["responses"][-6:]
            ],
            "remaining_model_calls": max_calls - state["calls"],
            "remaining_tool_calls": min(
                context.limits.max_tool_calls, budget.max_tool_calls
            )
            - state["tool_calls"],
            "validation_errors": state["errors"],
        }
        text, sizes = measure_json(
            data, fields={"tool_results": "history", "validation_errors": "feedback"}
        )
        prompt = measured_prompt(
            [
                (prompt_template("system"), "instructions"),
                (
                    prompt_template(
                        "correction" if state["errors"] else "investigation"
                    ),
                    "instructions",
                ),
                (
                    "\nOUTPUT_SCHEMA\n"
                    + json.dumps(
                        OrientationTurn.model_json_schema(), separators=(",", ":")
                    ),
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
                ("\nORIENTATION_DATA\n", "framing"),
                (text, sizes),
            ],
            stage="investigation",
            objective_id="orientation",
            correction=bool(state["errors"]),
        )
        if len(prompt) <= fit_cap or not working.reduce():
            return prompt
