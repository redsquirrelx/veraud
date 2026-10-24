# Project Architecture Pipeline

`server.pipelines.ProjectArchitecturePipeline` composes the focused repository agents
in one LangGraph for backend and CLI callers:

```text
orientation -> architecture -> diagram composition -> semantic review
  -> optional architect return -> revised diagram composition -> revalidation
```

The pipeline consumes one retained `RepositorySnapshot`. Every stage and feedback
round uses a fresh `RepositoryToolset` and evidence ledger over that snapshot. It
does not import CLI code, collect a second snapshot, create backend execution rows,
or own model clients.

## Backend composition

Construct your agents using backend-configured models. A shared `ModelGateway`
can be passed as `generate` to all three agents to share pacing, retries, provider
measurements, and total token accounting. Different role models are also supported;
when using separate gateways, aggregate provider accounting belongs to the caller.

```python
from pathlib import Path

from server.agents.project_analysis.project_architecture import ProjectArchitectureAgent
from server.agents.project_analysis.project_orientation import ProjectOrientationAgent
from server.agents.project_analysis.project_semantic_validation import ProjectSemanticValidationAgent
from server.runtimes.repository import ExecutionBudget
from server.pipelines import ProjectArchitecturePipeline
from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)

snapshot = await RepositoryAnalysisService().analyze(
    RepositoryAnalysisInput(root_path=str(checkout), max_files=5000, max_depth=30)
)
pipeline = ProjectArchitecturePipeline(
    ProjectArchitectureAgent(model, generate=gateway, on_event=progress),
    orientation=ProjectOrientationAgent(model, generate=gateway, on_event=progress),
    validator=ProjectSemanticValidationAgent(model, generate=gateway, on_event=progress),
    hooks=backend_hooks,
    on_event=progress,
)
result = await pipeline.run(
    snapshot,
    budget=ExecutionBudget(
        max_input_tokens_per_call=10000,
        max_tokens_per_objective=40000,
        max_total_tokens=80000,
    ),
    workspace_root=Path(workspace_root),
)
payload = result.model_dump(mode="json")
```

`model`, `gateway`, `progress`, `backend_hooks`, and workspace paths are supplied by
the backend adapter. The caller closes model clients in its own `finally` block.
Repository access retains the shared runtime's selected-checkout and source-only
boundaries. No HTTP routes or existing backend reporting contracts are replaced.

## Options and ownership

- `include_orientation=False`: start directly with architecture; orientation agent
  may be omitted.
- `validate_semantics=False`: omit semantic review; optional diagram composition
  still runs, and the validator may be omitted.
- `allow_return=False`: review once without returning to the architect.
- `include_diagram=False`: omit the dedicated model composition call (on by default
  in both HTTP and CLI; use `--no-diagram`). It selects from report references,
  performs no repository reads, and precedes semantic review.
- `resume_architecture=saved_result`: skip orientation and architecture investigation,
  verify the result's snapshot hash, and continue composition/review according to the
  requested flags. No source investigation is repeated.
- `deadline`: optional absolute `time.monotonic()` deadline shared with a caller's
  provider gateway. Otherwise the pipeline starts one deadline using
  `budget.max_elapsed_seconds`. Snapshot collection happens before this deadline
  unless the caller supplies an earlier one.
- `execute`: optional async wrapper accepting an awaitable, for tracing or heartbeat
  integration. It wraps each top-level stage, including the complete semantic cycle.

The initial semantic review has advisory token budgets throughout its calls and
provider retries. Revalidation retains strict admission. Token measurements and
budget advisories are preserved. Call/tool/output limits and the shared elapsed
deadline remain enforced. At most one architect return is allowed, currently only
when findings request missing evidence. A decisive rejection alone does not trigger
a return. If no architectural report was produced, semantic review is skipped.

## Typed result

`ProjectArchitecturePipelineResult` contains:
- `snapshot_hash`;
- `orientation`: optional orientation result;
- `architecture`: original architecture result;
- `semantic_validation`: optional original/revised report history and evaluations.
- `diagram`: optional rendered component view of the displayed report, including its
  structure, Mermaid source, claim/evidence annotations, and matching semantic verdicts.
  See [architecture diagrams](architecture-diagrams.md).
- `stages`: typed stage outcomes (`complete`, `partial`, `failed`, or `skipped`), with
  the original failure cause and provider HTTP status/attempt count when available.
- `diagram_composition`: the optional model selection result, base report hash,
  independent composition usage/telemetry, and any issues. A revised report's new
  selection is preserved in `semantic_validation.diagram_revision` before revalidation.

Convenience properties:
- `displayed_architecture`: revised report when one exists, otherwise original;
- `usable`: execution produced usable output, **not semantic acceptance**;
- `tool_calls`: sum across all executed roles and rounds.

Partial outputs returned by agents remain available in the result. Backend consumers
should examine the latest review's verdict, pending claims, and issues, and confirm
that it concerns the displayed report. `model_dump(mode="json")` preserves stage
outputs and history; convenience properties are not added to the serialized contract.

## Backend stage hooks

Implement `ProjectArchitecturePipelineHooks` with two async methods:

```python
async def on_stage_start(self, stage: str) -> None:
    ...  # Mark a backend-owned execution row running.

async def on_stage_result(self, stage: str, result: BaseModel) -> None:
    ...  # Persist the typed result, including partial outcomes.
```

Stage names are `orientation`, `architecture`, `diagram_composition`, and `semantic_validation`.
An optional `on_architecture_revision(result)` hook receives a revised report before
its diagram call, for persistence. Pass `diagram_architect=` to the constructor to
inject a separate composition model/gateway and isolate its provider failure state.
Without it, the library retains the supplied architect's gateway behavior.
Skipped stages invoke no start/result hooks. The semantic stage's result includes the entire
bounded feedback history. Detailed model/tool/retry and return events continue through
agents' and pipeline's `on_event` callbacks. Hook exceptions, unexpected stage failures,
timeouts, and external cancellation propagate to the caller; its service owns failed-row
cleanup. Result hooks are only called for stages that returned a result.

Adapters may additionally implement `on_stage_skip(stage: str, reason: str)` to close
backend-owned rows for skipped stages. This optional hook receives disabled stages
and downstream stages that cannot run after a terminal shared-provider failure;
`on_stage_start` and `on_stage_result` are not called for them. The pipeline emits
`{stage}_skipped` progress events with the reason. A different healthy stage gateway
may continue even when orientation's provider failed.

For compatibility, a skipped architecture stage has an empty failed `ArchitectureResult`
with a `stage_skipped` issue and zero usage. Its stage outcome is explicitly `skipped`,
and the original orientation result remains available. The CLI exports `pipeline_status`
and `pipeline_stages` and highlights the root failed stage, rather than attributing
the provider failure to an architect that never executed. Request telemetry preserves
`http_status` and `error_type` alongside the attempt count.

Graph state, deadlines, and ledgers are local to each invocation. Reusing a pipeline
sequentially does not reuse investigation evidence. For concurrent backend requests,
provide request-local agents/gateways because provider observers and guards are mutable.

## Code and verification

- `src/server/pipelines/project_architecture.py`: full graph, fresh tools, deadline,
  stage hooks, typed output.
- `src/server/pipelines/semantic_validation.py`: single-return coordinator and history.
- `src/server/repository_runner.py`: CLI collection, model lifecycle, presentation,
  and invocation of the shared pipeline.

Tests cover the real offline agent graphs, shared snapshot identity, independent ledgers,
feedback history, hook ordering, stage skipping, sequential reuse, deadlines, cancellation,
and architecture runner compatibility.
