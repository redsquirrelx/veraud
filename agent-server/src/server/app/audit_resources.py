"""Per-run provider cache and snapshot-bound repository-tool construction."""

from pathlib import Path

from config.agents.audit import audit_output_envelope
from server.config.schemas import ModelCredentials, ModelSettings
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.shared_tokens import SharedTokenBudget
from server.runtimes.repository.timing import ActiveDeadline
from server.runtimes.repository.tools import RepositoryToolset, ToolLimits


def audit_client(clients, settings: ModelSettings, credentials: ModelCredentials, factory):
    """Reuse one client for each resolved model/credential pair within the run."""
    key = (settings.model_dump_json(), credentials.api_key)
    if key not in clients:
        clients[key] = factory(settings, credentials)
    return clients[key]


def repository_tools(
    snapshot,
    root: Path,
    limits,
    total_tokens: int,
    timing: ActiveDeadline,
    token_budget: SharedTokenBudget,
    output_overrides,
    *,
    security: bool,
) -> RepositoryToolset:
    """Build fresh read-only tools with the selected attribute's existing limits."""
    budget = ExecutionBudget(
        max_model_calls=limits.max_model_calls,
        max_tool_calls=max(1, limits.max_tool_calls),
        max_total_tokens=total_tokens,
        max_tokens_per_objective=total_tokens,
        max_input_tokens_per_call=max(500, limits.max_context_characters // 2),
        max_output_tokens_per_call=audit_output_envelope(limits, output_overrides),
        max_elapsed_seconds=limits.timeout_seconds,
    )
    tool_limits = ToolLimits(compact=True)
    if security:
        budget = ExecutionBudget.model_validate(
            budget.model_dump()
            | {"max_retrieved_characters": limits.max_retrieved_characters}
        )
        tool_limits = ToolLimits(
            compact=True,
            max_source_lines=limits.max_source_lines,
            max_source_characters=limits.max_source_characters,
        )
    return RepositoryToolset(
        RepositoryContext(
            snapshot,
            RepositoryInput(
                snapshot_hash=snapshot.repository.snapshot_hash,
                budget=budget,
            ),
        ),
        workspace_root=root.parent,
        limits=tool_limits,
        token_budget=token_budget,
        timing=timing,
    )
