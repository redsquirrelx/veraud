"""Snapshot-bound orientation, architecture, and semantic review composition.

Callers own model clients, provider gateways, snapshot collection, and persistence.
Every invocation owns its graph state and tool ledgers; no CLI dependency is needed.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from ..agents.project_architecture import ProjectArchitectureAgent
from ..agents.project_architecture.schemas import ArchitectureResult
from ..agents.project_orientation import ProjectOrientationAgent
from ..agents.project_orientation.schemas import OrientationResult
from ..agents.project_semantic_validation import ProjectSemanticValidationAgent
from ..agents.repository_runtime import (
    ExecutionBudget,
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
)
from ..services.repository_analysis import RepositorySnapshot
from .semantic_validation import SemanticPipelineResult, validate_architecture_pipeline


class ProjectArchitecturePipelineHooks(Protocol):
    """Backend adapters can persist stage transitions without owning orchestration."""

    async def on_stage_start(self, stage: str) -> None: ...
    async def on_stage_result(self, stage: str, result: BaseModel) -> None: ...


class ProjectArchitecturePipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_hash: str
    orientation: OrientationResult | None = None
    architecture: ArchitectureResult
    semantic_validation: SemanticPipelineResult | None = None

    @property
    def displayed_architecture(self) -> ArchitectureResult:
        revised = (
            self.semantic_validation.revised_architecture
            if self.semantic_validation
            else None
        )
        return (
            revised
            if revised and revised.architecture is not None
            else self.architecture
        )

    @property
    def usable(self) -> bool:
        if self.architecture.completion_status == "failed":
            return False
        if self.semantic_validation:
            history = self.semantic_validation
            return history.validations[-1].completion_status != "failed" and (
                history.revised_architecture is None
                or history.revised_architecture.completion_status != "failed"
            )
        return True

    @property
    def tool_calls(self) -> int:
        total = self.architecture.usage.tool_calls + (
            self.orientation.usage.tool_calls if self.orientation else 0
        )
        if self.semantic_validation:
            total += sum(
                review.usage.tool_calls
                for review in self.semantic_validation.validations
            )
            if self.semantic_validation.revised_architecture:
                total += self.semantic_validation.revised_architecture.usage.tool_calls
        return total


class PipelineState(TypedDict, total=False):
    orientation: OrientationResult | None
    architecture: ArchitectureResult
    semantic_validation: SemanticPipelineResult | None


@dataclass(frozen=True)
class PipelineRuntime:
    snapshot: RepositorySnapshot
    budget: ExecutionBudget
    workspace_root: Path
    deadline: float
    include_orientation: bool
    validate_semantics: bool
    allow_return: bool
    execute: Callable[[Awaitable], Awaitable] | None

    def fresh_tools(self):
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Project architecture pipeline deadline exhausted.")
        return RepositoryToolset(
            RepositoryContext(
                snapshot=self.snapshot,
                input=RepositoryInput(
                    snapshot_hash=self.snapshot.repository.snapshot_hash,
                    budget=self.budget.model_copy(
                        update={"max_elapsed_seconds": remaining}
                    ),
                ),
            ),
            workspace_root=self.workspace_root,
        )


class ProjectArchitecturePipeline:
    """Compose focused agents; the first review has advisory token admission."""

    def __init__(
        self,
        architect: ProjectArchitectureAgent,
        *,
        orientation: ProjectOrientationAgent | None = None,
        validator: ProjectSemanticValidationAgent | None = None,
        hooks: ProjectArchitecturePipelineHooks | None = None,
        on_event=None,
    ):
        self.architect, self.orientation, self.validator = (
            architect,
            orientation,
            validator,
        )
        self.hooks, self.on_event = hooks, on_event
        graph = StateGraph(PipelineState, context_schema=PipelineRuntime)
        graph.add_node("orientation", self._orientation)
        graph.add_node("architecture", self._architecture)
        graph.add_node("semantic_validation", self._validation)
        graph.add_edge(START, "orientation")
        graph.add_edge("orientation", "architecture")
        graph.add_edge("architecture", "semantic_validation")
        graph.add_edge("semantic_validation", END)
        self.graph = graph.compile()

    async def run(
        self,
        snapshot: RepositorySnapshot,
        *,
        budget: ExecutionBudget,
        workspace_root: Path,
        include_orientation=True,
        validate_semantics=True,
        allow_return=True,
        deadline: float | None = None,
        execute=None,
    ):
        if include_orientation and self.orientation is None:
            raise ValueError("Orientation stage requires an orientation agent.")
        if validate_semantics and self.validator is None:
            raise ValueError("Semantic review requires a validator agent.")
        context = PipelineRuntime(
            snapshot,
            budget,
            Path(workspace_root),
            deadline
            if deadline is not None
            else monotonic() + budget.max_elapsed_seconds,
            include_orientation,
            validate_semantics,
            allow_return,
            execute,
        )
        state = await asyncio.wait_for(
            self.graph.ainvoke({}, context=context),
            max(0, context.deadline - monotonic()),
        )
        return ProjectArchitecturePipelineResult(
            snapshot_hash=snapshot.repository.snapshot_hash,
            orientation=state.get("orientation"),
            architecture=state["architecture"],
            semantic_validation=state.get("semantic_validation"),
        )

    async def _stage(self, stage, action, context):
        if self.on_event:
            self.on_event(stage + "_started", {})
        if self.hooks:
            await self.hooks.on_stage_start(stage)
        result = await context.execute(action()) if context.execute else await action()
        if self.hooks:
            await self.hooks.on_stage_result(stage, result)
        if self.on_event:
            self.on_event(
                stage + "_finished",
                {"status": getattr(result, "completion_status", "finished")},
            )
        return result

    async def _orientation(self, state, runtime):
        context = runtime.context
        if not context.include_orientation:
            return {"orientation": None}
        return {
            "orientation": await self._stage(
                "orientation",
                lambda: self.orientation.run(context.fresh_tools()),
                context,
            )
        }

    async def _architecture(self, state, runtime):
        context = runtime.context
        return {
            "architecture": await self._stage(
                "architecture",
                lambda: self.architect.run(
                    context.fresh_tools(), state.get("orientation")
                ),
                context,
            )
        }

    async def _validation(self, state, runtime):
        context = runtime.context
        if not context.validate_semantics or state["architecture"].architecture is None:
            return {"semantic_validation": None}
        # The caller wrapper retains tracing/heartbeats; hooks receive the full history.
        return {
            "semantic_validation": await self._stage(
                "semantic_validation",
                lambda: validate_architecture_pipeline(
                    state["architecture"],
                    validator=self.validator,
                    fresh_tools=context.fresh_tools,
                    architect=self.architect if context.allow_return else None,
                    orientation=state.get("orientation"),
                    on_event=self.on_event,
                ),
                context,
            )
        }
