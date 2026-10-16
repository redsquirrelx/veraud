"""Fit architectural evidence and navigation context before provider admission."""

import json

from ....runtimes.repository.telemetry import measure_json, measured_prompt
from ....runtimes.repository.token_budget import input_ratio
from ....runtimes.repository.tools import tool_signatures
from ....runtimes.repository.working_context import WorkingContext
from .context import contract_view, prompt_template
from .coverage import (
    application_coverage,
    relationship_coverage,
    relationship_recovery_tasks,
)
from .schemas import ArchitectureTurn

ALLOWED_TOOLS = {
    "list_files",
    "find_symbols",
    "get_source_excerpt",
    "list_relationships",
    "search_repository_text",
    "get_infrastructure",
    "get_evidence",
}


def prepare_prompt(state, context, maximum):
    budget = context.tools.context.input.budget
    working = WorkingContext(
        state["representation"],
        state["responses"],
        protected_file_ids=[
            item["file_id"]
            for bundle in state["representation"].get("investigation_bundles", [])[:1]
            for item in bundle["files"]
        ],
    )
    working.representation.pop("application_targets", None)
    working.representation.pop("investigation_bundles", None)
    paths = {
        source.id: source.path for source in context.tools.accessible_snapshot.files
    }
    evidence = [
        {
            "id": record.id,
            "file_id": record.file_id,
            "path": paths[record.file_id],
            "start_line": record.start_line,
            "end_line": record.end_line,
        }
        for record in context.tools.retrieved_evidence
        if record.kind == "source"
    ]
    inspected = {record["file_id"] for record in evidence}
    need_source = len(inspected) < min(2, len(paths))
    bundles = [
        bundle
        | {
            "files": [
                item
                | {
                    "source_evidence": [
                        {key: record[key] for key in ("id", "start_line", "end_line")}
                        for record in evidence
                        if record["file_id"] == item["file_id"]
                    ]
                }
                for item in bundle["files"]
            ]
        }
        for bundle in state["representation"].get("investigation_bundles", [])
    ]
    draft_units = (
        state["raw"].get("organization", []) if isinstance(state["raw"], dict) else []
    )
    if not isinstance(draft_units, list):
        draft_units = []
    schema = ArchitectureTurn.model_json_schema()
    # Diagram selection is a separate compact call; do not spend investigation
    # context/output tokens asking the model to duplicate its report structure.
    schema["$defs"]["ArchitectureReport"]["properties"].pop("diagram", None)
    for name in (
        "ArchitectureDiagram",
        "DiagramView",
        "DiagramDeviation",
        "DiagramNode",
        "DiagramEdge",
        "DiagramGroup",
    ):
        schema["$defs"].pop(name, None)
    contract = contract_view(schema)
    if need_source:
        contract = {
            "response_fields": {"tool_calls": "[RepositoryToolCall]"},
            "types": {"RepositoryToolCall": contract["types"]["RepositoryToolCall"]},
            "tool_call_example": {
                "tool_calls": [
                    {
                        "id": "read-1",
                        "name": "get_source_excerpt",
                        "arguments": {"path": "<candidate path>"},
                    }
                ]
            },
            "rules": "Request source inspection now. No architecture response until relevant implementation has been inspected.",
        }
    cap = min(
        context.limits.max_prompt_characters,
        int(budget.max_input_tokens_per_call / input_ratio(context.generate)) - 128,
    )
    fit_cap = cap if working.responses else cap - min(3000, cap // 4)
    coverage = application_coverage(context.tools, state["architecture"])
    while True:
        data = {
            "representation": working.representation,
            "tool_results": working.responses,
            "omitted_tool_results": working.omitted_results,
            "remaining_model_calls": maximum - state["calls"],
            "remaining_tool_calls": min(
                context.limits.max_tool_calls, budget.max_tool_calls
            )
            - state["tool_calls"],
            "validation_errors": state["errors"],
            "semantic_review_feedback": context.feedback,
            "required_action": "tool_calls: inspect implementation from different responsibilities"
            if need_source
            else "tool_calls OR architecture",
            "architect_inspected_file_count": len(inspected),
            "source_evidence_ledger": evidence,
            "application_coverage": coverage,
            "pending_relationship_tasks": relationship_recovery_tasks(
                context.tools,
                state["architecture"],
                state.get("relationship_actions", {}),
            )[:8],
            "relationship_recovery_actions": state.get("relationship_actions", {}),
            "relationship_coverage": [
                item
                | {
                    "pending_path_count": len(item["pending_paths"]),
                    "pending_paths": item["pending_paths"][:12],
                }
                for item in relationship_coverage(context.tools, state["architecture"])
            ],
            "closing_instruction": "Return architecture now with concrete responsibilities, connection mechanisms, separately cited supporting findings, closest_architecture and a developed, reasoned explanation. Use a precisely scoped hypothesis with limitations if the pattern is only plausible, or an unresolved no-clear-pattern conclusion. Do not label insufficient evidence supported. Retain valid findings and explicitly declare incomplete coverage."
            if state["finalizing"]
            else "Investigate representative flows and distinct architectural findings before closing; include developed responsibilities, connections, supporting_evidence, a pattern assessment and explanation, even if unresolved.",
            "application_targets": state["representation"].get(
                "application_targets", []
            ),
            "investigation_bundles": bundles,
            "draft_unit_names": [
                item.get("name") for item in draft_units if isinstance(item, dict)
            ][:8],
        }
        text, sizes = measure_json(
            data, fields={"tool_results": "history", "validation_errors": "feedback"}
        )
        prompt = measured_prompt(
            [
                (prompt_template("system"), "instructions"),
                (prompt_template("architecture_criteria"), "instructions"),
                (
                    prompt_template(
                        "correction" if state["errors"] else "investigation"
                    ),
                    "instructions",
                ),
                (
                    "\nOUTPUT_SCHEMA\n" + json.dumps(contract, separators=(",", ":")),
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
                ("\nARCHITECTURE_DATA\n", "framing"),
                (text, sizes),
            ],
            stage="investigation",
            objective_id=context.objective_id,
            correction=bool(state["errors"])
            and not state["evidence_recovery"]
            and not state["finalizing"],
        )
        if len(prompt) <= fit_cap or not working.reduce():
            return prompt, need_source
