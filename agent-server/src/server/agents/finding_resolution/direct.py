"""Direct HTTP entry point for finding resolution over a repository checkout.

This wrapper owns the host-side setup the library agent deliberately does not:
snapshot collection, the read-only repository toolset and the job envelope.
The investigation/evaluation contract itself stays in ``agent.py``.
"""

from pathlib import Path

from server.config.settings import resolve_workspace_root
from server.infrastructure.llm.chat import build_chat_model
from server.runtimes.direct import BaseAgent
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)

from .agent import FindingResolutionAgent
from .config import FindingResolutionConfig
from .schemas import FindingResolutionRunRequest, FindingResolutionRunResult

_COMPLETED_TERMINATIONS = {"investigations_completed", "no_findings"}


class FindingResolutionDirectAgent(BaseAgent[FindingResolutionRunRequest, FindingResolutionRunResult]):
    """Registered direct agent; requires a model and a workspace checkout."""

    agent_type = "finding_resolution"
    input_schema = FindingResolutionRunRequest
    output_schema = FindingResolutionRunResult

    async def run(self, input_data: FindingResolutionRunRequest) -> FindingResolutionRunResult:
        repository_path = str(Path(input_data.repository_path).expanduser().resolve())
        snapshot = await RepositoryAnalysisService().analyze(
            RepositoryAnalysisInput(root_path=repository_path)
        )
        if input_data.commit_hash and snapshot.repository.commit and (
            snapshot.repository.commit.lower() != input_data.commit_hash.lower()
        ):
            raise ValueError(
                "The checkout is not at the audited commit; select that project version "
                "before starting finding resolution."
            )

        config = FindingResolutionConfig(
            timeout_seconds=self.settings.timeout_seconds,
            max_output_tokens=min(self.model.settings.max_tokens, 4000),
        )
        budget = ExecutionBudget(
            max_model_calls=config.max_model_calls,
            max_tool_calls=config.max_tool_calls,
            max_total_tokens=config.max_total_tokens,
            max_elapsed_seconds=config.timeout_seconds,
            max_output_tokens_per_call=config.max_output_tokens,
        )
        tools = RepositoryToolset(
            RepositoryContext(
                snapshot,
                RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash, budget=budget),
            ),
            workspace_root=resolve_workspace_root(),
        )

        chat_model = getattr(self.model, "llm", None)
        if chat_model is None:
            chat_model = build_chat_model(self.model.settings, self.model.credentials)
        state = await FindingResolutionAgent(chat_model, config).run(
            input_data.library_request(), tools=tools
        )

        final = state.get("final_result")
        results = list(final.results) if final is not None else []
        termination = state.get("termination_reason")
        status = (
            "failed" if final is None
            else "partial" if (
                any(result.status == "inconclusive" for result in results)
                or termination not in _COMPLETED_TERMINATIONS
            )
            else "completed"
        )
        limitations = list(dict.fromkeys(state.get("limitations", [])))[:50]
        return FindingResolutionRunResult(
            status=status,
            source_audit_id=input_data.source_audit_id,
            commit_hash=input_data.commit_hash,
            snapshot_hash=snapshot.repository.snapshot_hash,
            results=results,
            limitations=limitations,
            consumption=state["consumption"],
        )
