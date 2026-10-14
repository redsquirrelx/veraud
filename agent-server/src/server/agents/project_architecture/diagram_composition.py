"""One compact architect call chooses a view after repository investigation."""

import asyncio
import hashlib
import json
from typing import Literal

from pydantic import model_validator

from ..repository_runtime.responses import (
    normalize_record_arrays,
    parse_json_value,
    validation_feedback,
)
from ..repository_runtime.results import execution_results
from ..repository_runtime.schemas import AgentContract, BudgetUsage, ExecutionIssue
from ..repository_runtime.telemetry import (
    ExecutionTelemetry,
    TextCallObserver,
    measured_prompt,
)
from ..repository_runtime.token_budget import TokenBudgetExceeded, admit_request
from ..repository_runtime.working_context import rejection_details
from .context import prompt_template
from .diagram import report_connections
from .schemas import ArchitectureDiagram, ArchitectureReport

MAX_PROMPT_CHARACTERS = 16000
MAX_RESPONSE_CHARACTERS = 12000
MAX_OUTPUT_TOKENS = 1200
MAX_STATEMENT_CHARACTERS = 300


class DiagramCompositionResult(AgentContract):
    snapshot_hash: str
    report_hash: str
    completion_status: Literal["complete", "failed"]
    diagram: ArchitectureDiagram | None = None
    execution_issues: tuple[ExecutionIssue, ...] = ()
    usage: BudgetUsage
    telemetry: ExecutionTelemetry

    @model_validator(mode="after")
    def outcome(self):
        if (self.diagram is not None) != (self.completion_status == "complete"):
            raise ValueError("Only a complete composition has an accepted diagram.")
        return self


def composition_data(report):
    def summary(claim):
        return {
            "statement": claim.statement[:MAX_STATEMENT_CHARACTERS],
            "truncated": len(claim.statement) > MAX_STATEMENT_CHARACTERS,
            "scope": claim.scope,
            "status": claim.status,
            "limitations": list(claim.limitations)[:2],
        }

    return {
        "units": [
            {
                "unit_ref": f"/organization/{index}",
                "name": unit.name,
                "responsibility": summary(unit.responsibility),
            }
            for index, unit in enumerate(report.organization)
        ],
        "connections": [
            {
                "claim_ref": pointer,
                "source_unit": edge.source_unit,
                "target_unit": edge.target_unit,
                "description": summary(edge.description),
            }
            for pointer, edge in report_connections(report)
        ],
        "explanation": summary(report.explanation) if report.explanation else None,
        "classification": {
            "pattern": report.closest_architecture.pattern,
            "assessment": summary(report.closest_architecture.assessment),
        }
        if report.closest_architecture
        else None,
    }


async def compose_diagram(
    agent, tools, original, *, objective_id="diagram_composition"
):
    tools.context.require_snapshot(original.snapshot_hash)
    if original.architecture is None or not original.architecture.organization:
        raise ValueError(
            "Diagram composition requires a report with organization units."
        )
    if tools.budget_usage.tool_calls or tools.retrieved_evidence:
        raise ValueError(
            "Diagram composition requires a fresh ledger; it does not retrieve source."
        )
    generate = (
        agent.generate
        if hasattr(agent.generate, "telemetry")
        else TextCallObserver(agent.generate)
    )
    budget = tools.context.input.budget
    text = json.dumps(
        original.architecture.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(text.encode()).hexdigest()
    prompt = measured_prompt(
        [
            (prompt_template("diagram"), "instructions"),
            (
                "\nOUTPUT_SCHEMA\n"
                + json.dumps(
                    ArchitectureDiagram.model_json_schema(), separators=(",", ":")
                ),
                "contracts",
            ),
            (
                "\nDIAGRAM_DATA\n"
                + json.dumps(
                    composition_data(original.architecture), separators=(",", ":")
                ),
                "metadata",
            ),
        ],
        stage="investigation",
        objective_id=objective_id,
    )
    prompt.max_output_tokens = min(MAX_OUTPUT_TOKENS, budget.max_output_tokens_per_call)
    issues, diagram, calls = (), None, 0

    def event(name, **values):
        if agent.on_event:
            agent.on_event(name, values)

    def admission(text, attempts=0):
        try:
            admit_request(generate, budget, text, objective_id, attempts)
        except TokenBudgetExceeded as error:
            if not agent.limits.soft_token_budgets:
                raise
            event(
                "budget_advisory",
                reason=str(error),
                **rejection_details(generate, budget, text, objective_id),
            )

    try:
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise TokenBudgetExceeded(
                f"Diagram composition exceeds its compact {MAX_PROMPT_CHARACTERS}-character prompt limit."
            )
        if getattr(generate, "stopped", False):
            raise RuntimeError("Provider stopped after a terminal failure.")
        admission(prompt)
        generate.request_guard = admission
        event(
            "diagram_composition_turn",
            objective=objective_id,
            max_turns=1,
            max_output_tokens=prompt.max_output_tokens,
        )
        calls = 1
        response = await asyncio.wait_for(
            generate(prompt),
            max(0, budget.max_elapsed_seconds - tools.context.elapsed_seconds),
        )
        value, pruned = normalize_record_arrays(
            parse_json_value(response, MAX_RESPONSE_CHARACTERS),
            ArchitectureDiagram.model_json_schema(),
        )
        if pruned:
            event("model_response_pruned", dropped=list(pruned))
        diagram = ArchitectureDiagram.model_validate(value)
        ArchitectureReport.model_validate(
            original.architecture.model_dump() | {"diagram": diagram}
        )
    except Exception as error:  # noqa: BLE001 - preserve the architecture at the provider/format boundary
        diagram = None
        if isinstance(error, ValueError):
            message = "; ".join(validation_feedback(error))
        elif isinstance(error, TokenBudgetExceeded):
            message = str(error)
        else:
            message = f"{type(error).__name__}: {str(error)[:1500]}"
        issues = (
            ExecutionIssue(
                id=f"issue:{objective_id}:composition",
                stage=objective_id,
                category=getattr(
                    error,
                    "category",
                    "invalid_diagram"
                    if isinstance(error, ValueError)
                    else type(error).__name__,
                ),
                message=message[:2000],
            ),
        )
    usage, telemetry = execution_results(tools, generate, calls, issues, objective_id)
    return DiagramCompositionResult(
        snapshot_hash=original.snapshot_hash,
        report_hash=digest,
        completion_status="complete" if diagram else "failed",
        diagram=diagram,
        execution_issues=issues,
        usage=usage,
        telemetry=telemetry,
    )
