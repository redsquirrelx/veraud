"""One bounded architectural return, preserving both reports and both reviews."""

from pydantic import BaseModel, Field, model_validator

from ..agents.project_architecture import ProjectArchitectureAgent
from ..agents.project_architecture.diagram_composition import DiagramCompositionResult
from ..agents.project_architecture.schemas import ArchitectureResult
from ..agents.project_semantic_validation import ProjectSemanticValidationAgent
from ..agents.project_semantic_validation.context import review_targets
from ..agents.project_semantic_validation.schemas import SemanticValidationResult
from ..agents.repository_runtime.schemas import AgentContract


class SemanticPipelineResult(BaseModel):
    model_config = AgentContract.model_config
    original_architecture: ArchitectureResult
    revised_architecture: ArchitectureResult | None = None
    validations: tuple[SemanticValidationResult, ...] = Field(
        min_length=1, max_length=2
    )
    return_count: int = Field(default=0, ge=0, le=1)
    diagram_revision: DiagramCompositionResult | None = None

    @model_validator(mode="after")
    def bounded_history(self):
        if self.diagram_revision is not None and (
            not self.return_count
            or self.diagram_revision.snapshot_hash
            != self.original_architecture.snapshot_hash
        ):
            raise ValueError(
                "A diagram revision requires an architectural return on the same snapshot."
            )
        if bool(self.return_count) != (self.revised_architecture is not None):
            raise ValueError(
                "A returned architecture must be preserved in revision history."
            )
        if self.validations[0].original_result != self.original_architecture:
            raise ValueError(
                "The first review must preserve the original architecture."
            )
        if (
            len(self.validations) == 2
            and self.validations[1].original_result != self.revised_architecture
        ):
            raise ValueError("The second review must concern the revised architecture.")
        return self


async def validate_architecture_pipeline(
    original,
    *,
    validator: ProjectSemanticValidationAgent,
    fresh_tools,
    architect: ProjectArchitectureAgent | None = None,
    orientation=None,
    on_event=None,
    execute=None,
    compose_revision=None,
):
    """fresh_tools must bind new ledgers to the same snapshot and remaining deadline."""

    async def run(awaitable):
        return await execute(awaitable) if execute else await awaitable

    first = await run(validator.run(fresh_tools(), original, soft_token_budgets=True))
    requests = [finding for finding in first.findings if finding.missing_evidence]
    if architect is not None and getattr(
        getattr(architect, "generate", None), "stopped", False
    ):
        if on_event and requests:
            on_event(
                "architecture_revision_skipped",
                {"reason": "Shared provider unavailable after a terminal failure."},
            )
        return SemanticPipelineResult(
            original_architecture=original, validations=(first,)
        )
    if not requests or architect is None:
        return SemanticPipelineResult(
            original_architecture=original, validations=(first,)
        )
    if on_event:
        on_event(
            "semantic_validation_return",
            {"round": 1, "targets": [item.target_id for item in requests]},
        )
    selected = {target.id: target for target in review_targets(fresh_tools(), original)}
    feedback = {
        "report_hash": first.report_hash,
        "requests": [
            {
                "target_id": item.target_id,
                "original_claim": selected[item.target_id].claim.model_dump(
                    mode="json"
                ),
                "verdict": item.verdict,
                "reason": item.reason,
                "missing_evidence": [
                    request.model_dump(mode="json") for request in item.missing_evidence
                ],
            }
            for item in requests
        ],
    }
    revised = await run(
        architect.run(
            fresh_tools(),
            orientation,
            feedback=feedback,
            objective_id="architecture_revision",
        )
    )
    if revised.architecture is None:
        return SemanticPipelineResult(
            original_architecture=original,
            revised_architecture=revised,
            validations=(first,),
            return_count=1,
        )
    diagram_revision = await compose_revision(revised) if compose_revision else None
    if diagram_revision is not None:
        revised = revised.model_copy(
            update={
                "architecture": revised.architecture.model_copy(
                    update={"diagram": diagram_revision.diagram}
                )
            }
        )
    second = await run(
        validator.run(fresh_tools(), revised, objective_id="semantic_revalidation")
    )
    return SemanticPipelineResult(
        original_architecture=original,
        revised_architecture=revised,
        validations=(first, second),
        return_count=1,
        diagram_revision=diagram_revision,
    )
