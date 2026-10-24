"""One compact architect call chooses a view after repository investigation."""

import asyncio
import hashlib
import json
from typing import Literal

from pydantic import model_validator

from ....runtimes.repository.responses import (
    normalize_record_arrays,
    parse_json_value,
    validation_feedback,
)
from ....runtimes.repository.results import execution_results
from ....runtimes.repository.schemas import AgentContract, BudgetUsage, ExecutionIssue
from ....runtimes.repository.telemetry import (
    ExecutionTelemetry,
    TextCallObserver,
    measured_prompt,
)
from ....runtimes.repository.token_budget import TokenBudgetExceeded, admit_request
from ....runtimes.repository.working_context import rejection_details
from .context import prompt_template
from .diagram import project_component_diagram, report_connections
from .schemas import ArchitectureDiagram, ArchitectureReport, DiagramView

MAX_PROMPT_CHARACTERS = 48000
MAX_RESPONSE_CHARACTERS = 48000
MAX_OUTPUT_TOKENS = 8000
MAX_STATEMENT_CHARACTERS = 900


class DiagramCompositionResult(AgentContract):
    snapshot_hash: str
    report_hash: str
    completion_status: Literal["complete", "failed"]
    diagram: ArchitectureDiagram | None = None
    execution_issues: tuple[ExecutionIssue, ...] = ()
    usage: BudgetUsage
    telemetry: ExecutionTelemetry
    composition_origin: Literal["model", "model_repaired", "host_fallback"] = "model"

    @model_validator(mode="after")
    def outcome(self):
        if (self.diagram is not None) != (self.completion_status == "complete"):
            raise ValueError("Only a complete composition has an accepted diagram.")
        return self


def required_views(report):
    kinds = ["structure", "dependencies"]
    if any(
        edge.kind == "calls" and edge.description.status == "supported"
        for _, edge in report_connections(report)
    ):
        kinds.append("flow")
    return kinds


def missing_views(report, diagram):
    views = [diagram, *diagram.views]
    missing = [
        kind
        for kind in required_views(report)
        if not any(view.view_kind == kind for view in views)
    ]
    for view in views:
        if (
            view.view_kind == "dependencies"
            and report_connections(report)
            and not view.edges
            and "dependencies" not in missing
        ):
            missing.append("dependencies")
        if (
            view.view_kind == "flow"
            and "flow" not in missing
            and (
                not view.edges
                or any(
                    edge.kind != "calls"
                    or not any(
                        pointer == edge.claim_ref
                        and connection.kind == "calls"
                        and connection.description.status == "supported"
                        for pointer, connection in report_connections(report)
                    )
                    for edge in view.edges
                )
            )
        ):
            missing.append("flow")
    return missing


def complete_views(report, candidate=None):
    """Guarantee report-backed views without inventing components or mechanisms."""
    base = project_component_diagram(report)
    links = report_connections(report)
    generated = {"structure": DiagramView(**base.model_dump(exclude={"views"}))}
    generated["dependencies"] = generated["structure"].model_copy(
        update={
            "title": "Reported dependencies and connections",
            "view_kind": "dependencies",
            "direction": "LR",
            "limitations": (
                "This view reproduces report connections; generic relationships are not proof of static dependencies or runtime calls.",
            )
            + (
                ()
                if links
                else (
                    "No connections were established; responsibilities are shown without invented arrows.",
                )
            ),
        }
    )
    names = {
        unit.name: f"unit_{index}" for index, unit in enumerate(report.organization)
    }
    edges = tuple(
        {
            "source": names[edge.source_unit],
            "target": names[edge.target_unit],
            "claim_ref": pointer,
            "kind": edge.kind,
        }
        for pointer, edge in links
        if edge.source_unit in names and edge.target_unit in names
    )
    generated["dependencies"] = DiagramView.model_validate(
        generated["dependencies"].model_dump() | {"edges": edges[:24]}
    )
    calls = [
        edge
        for edge in edges
        if edge["kind"] == "calls"
        and next(
            connection for pointer, connection in links if pointer == edge["claim_ref"]
        ).description.status
        == "supported"
    ]
    if calls:
        chain, visited = [], set()
        current = next(
            (
                edge["source"]
                for edge in calls
                if not any(other["target"] == edge["source"] for other in calls)
            ),
            calls[0]["source"],
        )
        visited.add(current)
        while edge := next(
            (
                edge
                for edge in calls
                if edge["source"] == current and edge["target"] not in visited
            ),
            None,
        ):
            chain.append(edge)
            current = edge["target"]
            visited.add(current)
        if not chain:
            chain = [calls[0]]
            visited = {calls[0]["source"], calls[0]["target"]}
        generated["flow"] = DiagramView.model_validate(
            {
                "title": "Representative supported invocation flow",
                "scope": "Explicit supported calls in the report; not a complete runtime trace.",
                "view_kind": "flow",
                "nodes": [node for node in base.nodes if node.id in visited],
                "edges": chain,
                "limitations": [
                    "Only a representative report-backed path is shown; timing, concurrency and unreported calls are not inferred."
                ],
            }
        )
    for kind, view in generated.items():
        annotations, omissions = [], []
        for index, deviation in enumerate(report.deviations):
            affected = [
                node.id
                for node in view.nodes
                if set(
                    report.organization[
                        int(node.unit_ref.rsplit("/", 1)[1])
                    ].responsibility.evidence_ids
                )
                & set(deviation.observed_decision.evidence_ids)
            ]
            if affected:
                annotations.append(
                    {
                        "deviation_ref": f"/deviations/{index}",
                        "node_ids": affected,
                        "explanation": "The reported deviation shares source evidence with these responsibilities; its placement requires semantic review.",
                    }
                )
            else:
                omissions.append(
                    f"Deviation {index + 1} could not be placed from shared evidence: {deviation.observed_decision.statement[:120]}"
                )
        generated[kind] = DiagramView.model_validate(
            view.model_dump()
            | {
                "deviations": annotations,
                "limitations": list(view.limitations)
                + omissions[: max(0, 10 - len(view.limitations))],
            }
        )
    available = [candidate, *candidate.views] if candidate else []
    selected = [
        next(
            (
                view
                for view in available
                if view.view_kind == kind
                and kind
                not in missing_views(
                    report, ArchitectureDiagram(**view.model_dump(exclude={"views"}))
                )
            ),
            generated[kind],
        )
        for kind in required_views(report)
    ]
    # Non-required views are retained only when a slot is available.
    selected.extend(
        view
        for view in available
        if view.view_kind not in required_views(report) and view.view_kind != "flow"
    )
    selected = selected[:3]
    primary = selected[0].model_dump(exclude={"views"})
    if "flow" not in required_views(report):
        primary["limitations"] = tuple(
            dict.fromkeys(
                [
                    "No explicit supported invocation was established; a runtime flow cannot be drawn from generic relationships or imports.",
                    *primary["limitations"],
                ]
            )
        )[:10]
    return ArchitectureDiagram(
        **primary,
        views=tuple(
            DiagramView(**view.model_dump(exclude={"views"})) for view in selected[1:]
        ),
    )


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
        "required_views": required_views(report),
        "flow_omission": None
        if "flow" in required_views(report)
        else "No explicit supported invocation was established in the report; do not turn imports or generic relationships into a runtime flow.",
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
                "kind": edge.kind,
            }
            for pointer, edge in report_connections(report)
        ],
        "explanation": summary(report.explanation) if report.explanation else None,
        "classification": {
            "pattern": report.closest_architecture.pattern,
            "assessment": summary(report.closest_architecture.assessment),
            "contrast_question": report.closest_architecture.contrast_question,
            "contrast_result": summary(report.closest_architecture.contrast_result)
            if report.closest_architecture.contrast_result
            else None,
        }
        if report.closest_architecture
        else None,
        "deviations": [
            {
                "deviation_ref": f"/deviations/{index}",
                "observed_decision": summary(item.observed_decision),
                "pattern_expectation": item.pattern_expectation,
                "explanation": item.explanation,
            }
            for index, item in enumerate(report.deviations)
        ],
        "supporting_findings": [summary(claim) for claim in report.supporting_evidence],
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
    candidate, origin = None, "model"

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

    for turn in range(2):
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
                max_turns=2,
                turn=turn + 1,
                max_output_tokens=prompt.max_output_tokens,
            )
            calls += 1
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
            candidate = diagram
            missing = missing_views(original.architecture, diagram)
            if missing:
                raise ValueError(
                    f"Required diagram views are missing or invalid: {', '.join(missing)}. Return a full primary structure view plus complementary views, with supported calls only for flow."
                )
            diagram = complete_views(original.architecture, diagram)
            origin = "model_repaired" if turn else "model"
            break
        except Exception as error:  # noqa: BLE001 - preserve the architecture at the provider/format boundary
            diagram = None
            previous_issues = issues
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
            if (
                previous_issues
                and isinstance(error, RuntimeError)
                and "after a terminal failure" in str(error)
            ):
                issues = previous_issues
                message = issues[0].message
            if (
                turn == 0
                and not getattr(generate, "stopped", False)
                and tools.context.elapsed_seconds < budget.max_elapsed_seconds
            ):
                event("diagram_composition_correction", errors=[message])
                prompt = measured_prompt(
                    [
                        (
                            "\nCORRECTION\n"
                            + message
                            + "\nProduce all required_views; preserve valid selections and references.",
                            "feedback",
                        ),
                        (str(prompt), "instructions"),
                    ],
                    stage="investigation",
                    objective_id=objective_id,
                    correction=True,
                )
                prompt.max_output_tokens = min(
                    MAX_OUTPUT_TOKENS, budget.max_output_tokens_per_call
                )
                continue
            diagram = complete_views(original.architecture, candidate)
            diagram = diagram.model_copy(
                update={
                    "limitations": (
                        "Required views were completed deterministically from the report after unsuccessful model composition.",
                        *diagram.limitations,
                    )[:10]
                }
            )
            ArchitectureReport.model_validate(
                original.architecture.model_dump() | {"diagram": diagram}
            )
            origin = "host_fallback"
            event(
                "diagram_views_completed",
                required_views=required_views(original.architecture),
                reason=message,
            )
    if origin != "host_fallback":
        issues = ()
    usage, telemetry = execution_results(tools, generate, calls, issues, objective_id)
    return DiagramCompositionResult(
        snapshot_hash=original.snapshot_hash,
        report_hash=digest,
        completion_status="complete" if diagram else "failed",
        diagram=diagram,
        execution_issues=issues,
        usage=usage,
        telemetry=telemetry,
        composition_origin=origin,
    )
