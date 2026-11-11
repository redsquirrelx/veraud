"""Standalone, read-only architecture-context agent."""

import asyncio

from config.agents import InvestigationConfig
from server.agent_services.budgeting.shared_tokens import SharedTokenBudget
from server.agent_services.budgeting.timing import ActiveDeadline
from server.infrastructure.llm.chat import build_chat_model
from server.runtimes.direct import BaseAgent
from server.runtimes.repository.budgeted_model import BudgetedModel
from server.runtimes.repository.schemas import ExecutionBudget
from server.services.document_indexing import DocumentIndexingService
from server.services.document_indexing.storage import default_database

from .schemas import ArchitectureContextInput, ArchitectureContextResult
from .workflow import build_workflow


class ArchitectureContextAgent(BaseAgent[ArchitectureContextInput, ArchitectureContextResult]):
    agent_type = "architecture_context"
    input_schema = ArchitectureContextInput
    output_schema = ArchitectureContextResult

    async def run(self, input_data: ArchitectureContextInput) -> ArchitectureContextResult:
        limits = InvestigationConfig(
            timeout_seconds=self.settings.timeout_seconds,
            max_output_tokens=self.model.settings.max_tokens,
        )
        tokens = SharedTokenBudget(limits.max_total_tokens)
        timing = ActiveDeadline(limits.timeout_seconds)
        # Read Git blobs at the explicit commit, never mutable checkout content.
        # Keep the index so persisted provenance remains resolvable on this host.
        service = DocumentIndexingService(default_database())
        index = await asyncio.to_thread(
            service.index_repository, input_data.root_path, input_data.commit_hash,
        )
        chat_model = getattr(self.model, "llm", None)
        if chat_model is None:
            chat_model = build_chat_model(self.model.settings, self.model.credentials)
        managed = BudgetedModel(chat_model, limits, tokens, timing) if index.documents else None
        budget = ExecutionBudget(
            max_tool_calls=limits.max_tool_calls,
            max_output_tokens_per_call=limits.max_output_tokens,
            max_elapsed_seconds=limits.timeout_seconds,
        )
        if managed is not None and self.on_usage is not None:
            async def report(gateway):
                await self.on_usage(gateway, budget)
            managed.gateway.on_usage = report
        graph = build_workflow(service, managed, budget)
        state = await graph.ainvoke(
            {"document_index": service.get_index(index.index_id)},
            config={"recursion_limit": max(25, 3 * budget.max_tool_calls + 4)},
        )
        return ArchitectureContextResult.model_validate(state["result"])
