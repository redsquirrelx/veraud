"""One budgeted cognitive call to plan retrieval, without executing it."""

import json
from importlib.resources import files
from typing import get_args

from server.config.token_budget import effective_token_budget_policy
from server.runtimes.investigation.structured import parse_structured
from server.runtimes.repository.budgeted_model import BudgetedModel
from server.runtimes.repository.telemetry import measure_json, measured_prompt

from .schemas import RetrievalCategory, RetrievalPlan, RetrievalRecord, task_key
from .state import ArchitectureContextState

_CATEGORY_PATH_HINTS = {
    "architectural_style": (
        "architecture",
        "style",
        "pattern",
        "arquitect",
        "estilo",
        "patron",
    ),
    "components": ("component", "module", "service", "modulo", "servicio"),
    "responsibilities": ("responsib", "ownership", "owner"),
    "relationships": ("relation", "dependenc", "integrat", "interact", "relacion"),
    "constraints": ("constraint", "restric", "rule", "regla", "limit"),
    "interfaces_and_contracts": (
        "interface",
        "interfaz",
        "api",
        "endpoint",
        "contract",
        "contrat",
        "schema",
        "esquema",
        "protocol",
        "operation",
        "signature",
    ),
    "architectural_decisions": ("decision", "adr", "rfc"),
}


def _recent(items: list[dict], character_limit: int) -> tuple[list[dict], int]:
    """A bounded suffix for the prompt; authoritative history stays in state."""
    selected = []
    size = 2
    for item in reversed(items):
        length = len(json.dumps(item)) + 2
        if size + length > character_limit:
            break
        selected.append(item)
        size += length
    return list(reversed(selected)), len(items) - len(selected)


def _task_view(item: RetrievalRecord | object) -> dict:
    task = item.task if isinstance(item, RetrievalRecord) else item
    view = task.model_dump(mode="json")
    if isinstance(item, RetrievalRecord):
        view.update(
            status=item.status,
            executed=item.executed,
            section_ids=item.section_ids,
        )
    return view


async def plan_retrieval(
    state: ArchitectureContextState, *, model: BudgetedModel | None = None
) -> ArchitectureContextState:
    """The host owns the shared model/token/deadline budget across iterations.

    Uses the runtime's schema-validated JSON output path. Invalid plans propagate
    rather than triggering another LLM call or silently repairing invented paths.
    Retrieval records attempted operations in retrieval_history; the host updates needs.
    """
    if state.get("document_discovery_status") == "error":
        raise ValueError("Cannot plan retrieval from an unavailable document catalog")
    documents = state["documents"]
    pending = state.get("pending_categories", list(get_args(RetrievalCategory)))
    if not documents or not pending:
        return {"retrieval_plan": RetrievalPlan(tasks=[])}
    if model is None:
        raise ValueError("A budgeted model is required for nonempty retrieval planning")

    records = state.get("retrieval_history", [])
    executed = [
        item.task if isinstance(item, RetrievalRecord) else item
        for item in records
        if not isinstance(item, RetrievalRecord) or item.executed
    ]
    planned = state["retrieval_plan"].tasks if state.get("retrieval_plan") else []
    previous = [*executed, *planned]
    # Compact path/line metadata only, with deterministic navigation priority.
    menu = []
    size = 0
    for document in sorted(
        documents,
        key=lambda doc: (
            -sum(
                any(
                    term in doc.path.casefold()
                    for term in _CATEGORY_PATH_HINTS[category]
                )
                for category in pending
            ),
            doc.path,
        ),
    ):
        entry = [document.path, document.line_count]
        length = len(json.dumps(entry))
        if size + length > model.limits.max_context_characters // 3:
            continue
        menu.append(entry)
        size += length + 2
    # Separate attempts from intentions; neither demonstrates recovered knowledge.
    history_budget = model.limits.max_context_characters // 9
    executed_view, omitted_executed = _recent(
        [
            _task_view(item)
            for item in records
            if not isinstance(item, RetrievalRecord) or item.executed
        ],
        history_budget,
    )
    executed_keys = {task_key(task) for task in executed}
    planned_view, omitted_planned = _recent(
        [_task_view(task) for task in planned if task_key(task) not in executed_keys],
        history_budget,
    )
    processed_ids = set(state.get("processed_section_ids", []))
    processed_paths = sorted(
        {
            section.path
            for section in state.get("retrieved_sections", [])
            if section.section_id in processed_ids
        }
    )
    processed_view, omitted_processed = _recent(
        [{"path": path} for path in processed_paths],
        model.limits.max_context_characters // 12,
    )
    issue_view = [
        {
            "category": issue.category,
            "kind": issue.kind,
            "question": issue.question,
            "section_ids": issue.section_ids,
            "document_references": issue.document_references,
        }
        for issue in state.get("knowledge_issues", [])
    ]
    suggestion_view = [
        _task_view(task)
        for task in state.get("retrieval_suggestions", RetrievalPlan(tasks=[])).tasks
    ]
    # Open issues and their references are essential planning context. If they alone
    # exceed the request budget, fail closed rather than dropping uncertainty or
    # sending an oversized prompt.
    issue_size = len(json.dumps(issue_view, ensure_ascii=False))
    if issue_size > model.limits.max_context_characters // 3:
        return {
            "retrieval_plan": RetrievalPlan(tasks=[]),
            "context_stop_reason": "planning_context_exhausted",
        }
    context, sizes = measure_json(
        {
            "pending_categories": pending,
            "catalog_path_line_pairs": menu,
            "omitted_documents": len(documents) - len(menu),
            "processed_document_paths": [item["path"] for item in processed_view],
            "omitted_processed_documents": omitted_processed,
            "executed_tasks": executed_view,
            "planned_not_executed": planned_view,
            "open_issues": issue_view,
            "retrieval_suggestions": suggestion_view,
            "omitted_history": {
                "executed_tasks": omitted_executed,
                "planned_not_executed": omitted_planned,
            },
        },
        fields={
            "executed_tasks": "history",
            "planned_not_executed": "history",
            "open_issues": "history",
            "retrieval_suggestions": "history",
        },
    )
    instructions = (
        files(__package__)
        .joinpath("prompts", "plan_retrieval.md")
        .read_text(encoding="utf-8")
    )
    prompt = measured_prompt(
        [
            (instructions + "\nResponse schema:\n", "instructions"),
            (json.dumps(RetrievalPlan.model_json_schema()), "contracts"),
            ("\nRetrieval context:\n", "framing"),
            (context, sizes),
        ],
        stage="planning",
    )
    if len(prompt) > model.limits.max_context_characters:
        return {
            "retrieval_plan": RetrievalPlan(tasks=[]),
            "context_stop_reason": "planning_context_exhausted",
        }
    if state.get("retrieval_round", 0):
        # Preserve accumulated state when a later round cannot be admitted.
        reserve = len(prompt) + model.output_limit
        if (
            (
                not effective_token_budget_policy().unlimited_token_budget
                and model.attempts >= model.limits.max_model_calls
            )
            or model.timing.remaining <= 0
            or (
                not effective_token_budget_policy().unlimited_token_budget
                and (
                    reserve > model.tokens.remaining
                    or model.tokens.used + reserve > model.limits.max_total_tokens
                )
            )
        ):
            return {
                "retrieval_plan": RetrievalPlan(tasks=[]),
                "context_stop_reason": "planning_budget_exhausted",
            }
    response = await model.call(prompt, schema=RetrievalPlan)
    parsed = parse_structured(response, RetrievalPlan, native=False)
    plan = RetrievalPlan.model_validate(
        parsed.model_dump(),
        context={
            "paths": {document.path for document in documents},
            "previous_tasks": previous,
            "pending_categories": pending,
        },
    )
    return {
        "retrieval_plan": plan,
        "retrieval_round": state.get("retrieval_round", 0) + 1,
    }
