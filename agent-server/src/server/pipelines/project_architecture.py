"""Snapshot-bound orientation, architecture, and semantic review composition.

Callers own model clients, provider gateways, snapshot collection, and persistence.
Every invocation owns its graph state and tool ledgers; no CLI dependency is needed.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from ..agents.project_architecture import ProjectArchitectureAgent
from ..agents.project_architecture.diagram import (
    RenderedArchitectureDiagram,
    render_diagram,
)
from ..agents.project_architecture.diagram_composition import DiagramCompositionResult
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
from ..agents.repository_runtime.schemas import BudgetUsage, ExecutionIssue
from ..agents.repository_runtime.telemetry import ExecutionTelemetry
from ..services.repository_analysis import RepositorySnapshot
from .semantic_validation import SemanticPipelineResult, revision_feedback


class ProjectArchitecturePipelineHooks(Protocol):
    """Backend adapters can persist stage transitions without owning orchestration."""

    async def on_stage_start(self, stage: str) -> None: ...
    async def on_stage_result(self, stage: str, result: BaseModel) -> None: ...


class PipelineStageOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal[
        "orientation", "architecture", "diagram_composition", "semantic_validation"
    ]
    status: Literal["complete", "partial", "failed", "skipped"]
    reason: str | None = None


class ProjectArchitecturePipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_hash: str
    orientation: OrientationResult | None = None
    architecture: ArchitectureResult
    semantic_validation: SemanticPipelineResult | None = None
    diagram: RenderedArchitectureDiagram | None = None
    stages: tuple[PipelineStageOutcome, ...] = ()
    diagram_composition: DiagramCompositionResult | None = None

    @property
    def completion_status(self):
        if not self.usable:
            return "failed"
        if (
            self.semantic_validation
            and self.semantic_validation.diagram_revision
            and self.semantic_validation.diagram_revision.completion_status == "failed"
        ):
            return "partial"
        return (
            "partial"
            if any(stage.status in {"partial", "failed"} for stage in self.stages)
            else "complete"
        )

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

    @property
    def model_calls(self) -> int:
        total = self.architecture.usage.model_calls + (
            self.orientation.usage.model_calls if self.orientation else 0
        )
        if self.diagram_composition:
            total += self.diagram_composition.usage.model_calls
        if self.semantic_validation:
            total += sum(
                review.usage.model_calls
                for review in self.semantic_validation.validations
            )
            if self.semantic_validation.revised_architecture:
                total += self.semantic_validation.revised_architecture.usage.model_calls
            if self.semantic_validation.diagram_revision:
                total += self.semantic_validation.diagram_revision.usage.model_calls
        return total


class PipelineState(TypedDict, total=False):
    orientation: OrientationResult | None
    architecture: ArchitectureResult
    semantic_validation: SemanticPipelineResult | None
    stages: tuple[PipelineStageOutcome, ...]
    diagram_composition: DiagramCompositionResult | None
    revised_architecture: ArchitectureResult | None
    diagram_revision: DiagramCompositionResult | None
    revision_feedback: dict | None
    return_count: int
    route: str


@dataclass(frozen=True)
class PipelineRuntime:
    snapshot: RepositorySnapshot
    budget: ExecutionBudget
    workspace_root: Path
    deadline: float
    include_orientation: bool
    validate_semantics: bool
    allow_return: bool
    include_diagram: bool
    resume_architecture: ArchitectureResult | None
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
        diagram_architect: ProjectArchitectureAgent | None = None,
        hooks: ProjectArchitecturePipelineHooks | None = None,
        on_event=None,
    ):
        self.architect, self.orientation, self.validator = (
            architect,
            orientation,
            validator,
        )
        self.hooks, self.on_event = hooks, on_event
        self.diagram_architect = diagram_architect or architect
        graph = StateGraph(PipelineState, context_schema=PipelineRuntime)
        graph.add_node("orientation", self._orientation)
        graph.add_node("architecture", self._architecture)
        graph.add_node("diagram_composition", self._diagram)
        graph.add_node("semantic_validation", self._validation)
        graph.add_edge(START, "orientation")
        graph.add_edge("orientation", "architecture")
        graph.add_edge("architecture", "diagram_composition")
        graph.add_edge("diagram_composition", "semantic_validation")
        graph.add_conditional_edges(
            "semantic_validation",
            lambda state: state.get("route", "finish"),
            {"revise": "architecture", "finish": END},
        )
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
        include_diagram=True,
        resume_architecture: ArchitectureResult | None = None,
        deadline: float | None = None,
        execute=None,
    ):
        if resume_architecture is not None:
            if resume_architecture.snapshot_hash != snapshot.repository.snapshot_hash:
                raise ValueError(
                    "Saved report does not match the current repository snapshot."
                )
            if resume_architecture.architecture is None:
                raise ValueError("Saved result has no architectural report to resume.")
            include_orientation = False
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
            include_diagram,
            resume_architecture,
            execute,
        )
        state = await asyncio.wait_for(
            self.graph.ainvoke({}, context=context),
            max(0, context.deadline - monotonic()),
        )
        result = ProjectArchitecturePipelineResult(
            snapshot_hash=snapshot.repository.snapshot_hash,
            orientation=state.get("orientation"),
            architecture=state["architecture"],
            semantic_validation=state.get("semantic_validation"),
            stages=state.get("stages", ()),
            diagram_composition=state.get("diagram_composition"),
        )
        displayed = result.displayed_architecture
        review = (
            result.semantic_validation.validations[-1]
            if result.semantic_validation
            else None
        )
        findings = (
            review.findings if review and review.original_result == displayed else ()
        )
        return result.model_copy(
            update={
                "diagram": render_diagram(
                    displayed,
                    findings=findings,
                    report_origin="original"
                    if displayed is result.architecture
                    else "revised",
                )
            }
        )

    async def _stage(self, stage, action, context, *, publish=True):
        if self.on_event:
            self.on_event(stage + "_started", {})
        if self.hooks:
            await self.hooks.on_stage_start(stage)
        result = await context.execute(action()) if context.execute else await action()
        if self.hooks and publish:
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
            return {
                "orientation": None,
                "stages": (await self._skip("orientation", "Disabled by caller."),),
            }
        result = await self._stage(
            "orientation",
            lambda: self.orientation.run(context.fresh_tools()),
            context,
        )
        return {
            "orientation": result,
            "stages": (self._outcome("orientation", result),),
        }

    async def _architecture(self, state, runtime):
        context = runtime.context
        if state.get("revision_feedback"):
            result = await self._stage(
                "architecture",
                lambda: self.architect.run(
                    context.fresh_tools(),
                    state.get("orientation"),
                    feedback=state["revision_feedback"],
                    objective_id="architecture_revision",
                ),
                context,
            )
            checkpoint = getattr(self.hooks, "on_architecture_revision", None)
            if checkpoint:
                await checkpoint(result)
            return {
                "revised_architecture": result,
                "return_count": 1,
                "stages": (
                    *state.get("stages", ()),
                    self._outcome("architecture", result),
                ),
            }
        if context.resume_architecture is not None:
            if self.hooks:
                await self.hooks.on_stage_result(
                    "architecture", context.resume_architecture
                )
            return {
                "architecture": context.resume_architecture,
                "stages": (
                    *state.get("stages", ()),
                    await self._skip(
                        "architecture", "Resumed from a snapshot-matching saved report."
                    ),
                ),
            }
        if getattr(getattr(self.architect, "generate", None), "stopped", False):
            reason = "Shared provider unavailable after an earlier terminal failure."
            result = ArchitectureResult(
                snapshot_hash=context.snapshot.repository.snapshot_hash,
                completion_status="failed",
                usage=BudgetUsage(),
                telemetry=ExecutionTelemetry(),
                execution_issues=(
                    ExecutionIssue(
                        id="issue:pipeline:architecture:skipped",
                        stage="architecture",
                        category="stage_skipped",
                        message=reason,
                    ),
                ),
            )
            return {
                "architecture": result,
                "stages": (
                    *state.get("stages", ()),
                    await self._skip("architecture", reason),
                ),
            }
        result = await self._stage(
            "architecture",
            lambda: self.architect.run(context.fresh_tools(), state.get("orientation")),
            context,
        )
        return {
            "architecture": result,
            "stages": (*state.get("stages", ()), self._outcome("architecture", result)),
        }

    async def _validation(self, state, runtime):
        context = runtime.context
        revised = state.get("revised_architecture")
        if revised is not None and revised.architecture is None:
            history = state["semantic_validation"].model_copy(
                update={
                    "revised_architecture": revised,
                    "return_count": 1,
                }
            )
            if self.hooks:
                await self.hooks.on_stage_result("semantic_validation", history)
            return {
                "semantic_validation": history,
                "route": "finish",
            }
        if not context.validate_semantics or state["architecture"].architecture is None:
            reason = (
                "Disabled by caller."
                if not context.validate_semantics
                else "No architecture report was produced."
            )
            return {
                "semantic_validation": None,
                "stages": (
                    *state.get("stages", ()),
                    await self._skip("semantic_validation", reason),
                ),
            }
        if getattr(getattr(self.validator, "generate", None), "stopped", False):
            history = (
                state["semantic_validation"].model_copy(
                    update={
                        "revised_architecture": revised,
                        "return_count": state.get("return_count", 0),
                        "diagram_revision": state.get("diagram_revision"),
                    }
                )
                if revised
                else None
            )
            if history and self.hooks:
                await self.hooks.on_stage_result("semantic_validation", history)
            return {
                "semantic_validation": history,
                "route": "finish",
                "stages": (
                    *state.get("stages", ()),
                    await self._skip(
                        "semantic_validation",
                        "Shared provider unavailable after an earlier terminal failure.",
                    ),
                ),
            }

        async def review_once():
            review = await self.validator.run(
                context.fresh_tools(),
                revised or state["architecture"],
                **(
                    {"objective_id": "semantic_revalidation"}
                    if revised
                    else {"soft_token_budgets": True}
                ),
            )
            return SemanticPipelineResult(
                original_architecture=state["architecture"],
                revised_architecture=revised,
                validations=(*state["semantic_validation"].validations, review)
                if revised
                else (review,),
                return_count=state.get("return_count", 0),
                diagram_revision=state.get("diagram_revision"),
            )

        result = await self._stage(
            "semantic_validation",
            review_once,
            context,
            publish=False,
        )
        feedback = None
        if context.allow_return and not state.get("return_count", 0):
            feedback = revision_feedback(result.validations[-1], context.fresh_tools())
            if feedback and getattr(
                getattr(self.architect, "generate", None), "stopped", False
            ):
                if self.on_event:
                    self.on_event(
                        "architecture_revision_skipped",
                        {
                            "reason": "Shared provider unavailable after a terminal failure."
                        },
                    )
                feedback = None
        if feedback and self.on_event:
            self.on_event(
                "semantic_validation_return",
                {
                    "round": 1,
                    "targets": [item["target_id"] for item in feedback["requests"]],
                },
            )
        if not feedback and self.hooks:
            await self.hooks.on_stage_result("semantic_validation", result)
        return {
            "semantic_validation": result,
            "revision_feedback": feedback,
            "route": "revise" if feedback else "finish",
            "stages": (
                *state.get("stages", ()),
                self._outcome("semantic_validation", result.validations[-1]),
            ),
        }

    async def _diagram(self, state, runtime):
        context = runtime.context
        revised = state.get("revised_architecture")
        if revised is not None:
            composition = (
                await self._compose_revision(revised, context)
                if context.include_diagram
                else None
            )
            if composition is not None:
                revised = revised.model_copy(
                    update={
                        "architecture": revised.architecture.model_copy(
                            update={"diagram": composition.diagram}
                        ),
                    }
                )
            return {"revised_architecture": revised, "diagram_revision": composition}
        original = state["architecture"]
        report = original.architecture
        reason = None
        if not context.include_diagram:
            reason = "Disabled by caller."
        elif report is None or not report.organization:
            reason = "No organization units available for diagram composition."
        elif report.diagram is not None:
            reason = "The report already includes an authored diagram."
        if reason:
            return {
                "diagram_composition": None,
                "stages": (
                    *state.get("stages", ()),
                    await self._skip("diagram_composition", reason),
                ),
            }
        composition = await self._stage(
            "diagram_composition",
            lambda: self.diagram_architect.compose_diagram(
                context.fresh_tools(), original
            ),
            context,
        )
        amended = original.model_copy(
            update={
                "architecture": report.model_copy(
                    update={"diagram": composition.diagram}
                )
            }
        )
        return {
            "architecture": amended,
            "diagram_composition": composition,
            "stages": (
                *state.get("stages", ()),
                self._outcome("diagram_composition", composition),
            ),
        }

    async def _compose_revision(self, revised, context):
        if (
            revised.architecture is None
            or not revised.architecture.organization
            or revised.architecture.diagram is not None
        ):
            return None
        if self.on_event:
            self.on_event("diagram_revision_started", {})
        action = self.diagram_architect.compose_diagram(
            context.fresh_tools(), revised, objective_id="diagram_revision"
        )
        result = await context.execute(action) if context.execute else await action
        if self.on_event:
            self.on_event(
                "diagram_revision_finished", {"status": result.completion_status}
            )
        return result

    async def _skip(self, stage, reason):
        if self.on_event:
            self.on_event(stage + "_skipped", {"reason": reason})
        hook = getattr(self.hooks, "on_stage_skip", None)
        if hook:
            await hook(stage, reason)
        return PipelineStageOutcome(stage=stage, status="skipped", reason=reason)

    @staticmethod
    def _outcome(stage, result):
        failed = next(
            (
                call
                for call in reversed(result.telemetry.model_calls)
                if call.status == "failed"
            ),
            None,
        )
        reason = None
        if failed:
            cause = (
                f"HTTP {failed.http_status}"
                if failed.http_status
                else failed.error_type or "request failure"
            )
            reason = (
                f"Provider {cause}; call failed after {failed.attempts} attempt(s)."
            )
        elif result.execution_issues:
            reason = "; ".join(
                f"{issue.category}: {issue.message}"
                for issue in result.execution_issues
            )
        return PipelineStageOutcome(
            stage=stage, status=result.completion_status, reason=reason
        )
