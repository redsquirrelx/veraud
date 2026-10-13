# Investigation Planning (Phase 3)

The project analyst now has a runnable LangGraph planning subgraph:

```text
build_investigation_candidates
    -> propose_investigation_plan
    -> validate_and_prioritize_plan
          -> propose_investigation_plan (bounded correction)
          -> END (ready or failed)
```

Planning produces an auditable investigation queue, not a functional report.
Investigation execution and finding validation are phase 4.

## Use

```python
from server.agents.project_analysis import InvestigationPlanner

# tools is a RepositoryToolset bound to the selected workspace checkout.
# model is caller-owned and exposes async generate(message: str) -> str.
state = await InvestigationPlanner(model).plan(tools)
if state["planning_status"] == "ready":
    plan = state["investigation_plan"]
    queue = state["investigation_queue"]
else:
    issues = state["execution_issues"]
```

The planner is compatible with the existing text-generation model interface.
An optional `generate` callable can wrap model generation for tracing. The
caller retains ownership of provider clients and cleanup. The graph is compiled
without persistence/checkpointers, and a supplied state must match the bound
execution input.

## Deterministic Candidate Catalog

`build_investigation_candidates(tools, limits)` consumes only the toolset's
documentation-filtered snapshot. It generates candidates for:

- Project orientation, including uncertain package/example/tooling roles.
- Startup, commands, and recognized public API entrypoints.
- Related HTTP/page entrypoints grouped by project, kind, and source location.
- Top-level definitions whose public API status requires investigation.
- Files imported by multiple distinct files, as shared-component leads.
- Declared/observed infrastructure integrations whose usage needs verification.

Candidates have stable IDs, project references, structural seeds, descriptions,
and limitations. No source text or narrative documentation enters the catalog.
Metadata from allowed configuration remains untrusted data.

Library exports are not treated as equivalent to embedded example applications.
Example/test paths within a project contribute representative-flow candidates,
and core paths are offered before sample paths within the same tier/project.
These are path heuristics, not established functional roles. A separate example
project still receives its own orientation and startup candidates.

The full catalog remains available for audit. At most 100 candidates and 12 seeds
per candidate are offered by default. Offering is round-robin across projects
within priority tiers, with orientation first. Inaccessible projects and
catalog/prompt omissions receive explicit deferred decisions.

## Model Proposal

The model receives:

- Bounded repository/technology/coverage metadata.
- Offered candidates and seed metadata such as symbol names, paths, routes,
  entrypoint kinds, and command targets.
- Project IDs requiring orientation within available slots.
- `InvestigationProposal` JSON schema and investigation constraints.
- Actionable feedback after a rejected proposal.

It proposes `ProposedInvestigation` records pairing candidate IDs with objectives,
questions, report sections, reasons, deliverables, completion criteria, and effort
hints. Optional `CandidateOmission` records explain rejected/deferred candidates.
The model cannot replace the deterministic catalog or select arbitrary seeds.

Prompts explicitly treat repository metadata as data rather than instructions.
Initial functional labels are provisional; imports do not establish calls,
declared dependencies do not establish usage, and implementations do not prove
runtime selection. Architectural compliance is outside this planner's objective.

## Validation and Priority

`validate_and_prioritize_plan(...)` checks:

- Offered candidate IDs and valid structural seeds.
- Project and priority-tier consistency within grouped objectives.
- No fabricated prior findings or blockers in the initial plan.
- Unique objective IDs and distinct candidate assignments.
- Normalized duplicate objectives (project, seeds, report sections, objective text).
- Orientation coverage before functional exploration.
- Investigation count limits and typed snapshot references.

Duplicates are removed with audit reasons. Missing orientation or invalid
references cause bounded model correction; they are not silently accepted.

Queue ordering uses:

1. Ordered tiers: orientation, startup, representative flow, shared/integration,
   material uncertainty.
2. Stable project-path ordering for required orientation when slots are limited.
3. Project diversity within remaining tiers.
4. Core versus sample/test structural path hints.
5. New source locations, resolving symbol/entrypoint seeds to their source paths.
6. Model-proposed effort hints and stable identifier ties.

Structural novelty is a proxy for behavioral diversity, not semantic proof.
Effort is a planning hint, not measured cost. Semantic quality of objectives and
questions requires annotated evaluation.

Every candidate receives an accepted, grouped, deferred, or rejected decision.
Budget trimming records why otherwise proposed objectives were deferred. Model
omissions preserve their reasons; unselected offered candidates are deferred.

## Follow-Up Admission

`admit_followups(tools, plan, findings, proposals, usage=...)` is deterministic.
The caller must supply accepted findings, not arbitrary model drafts.

- Require valid origin finding IDs belonging to the accepted plan.
- Require accessible seeds in the same checkout and project orientation coverage.
- Validate blockers against unfinished accepted investigations.
- Inherit a higher priority tier when the follow-up blocks that investigation.
- Schedule a prerequisite follow-up before its blocked target; reject cycles.
- Reject duplicates and record investigation/execution-budget deferrals.
- Preserve candidate/decision provenance and idempotent candidate replays.

The full plan remains an audit record. Phase 4 will filter completed targets when
selecting the next investigation. Supply cumulative model usage so follow-up
admission respects the report-call reserve.

## Limits and Failure Semantics

Default planning limits are 60,000 prompt characters and 40,000 response
characters. Prompt construction reduces the offered catalog to fit and records
omissions. Source content is never included in the planning prompt.

Model calls count toward `BudgetUsage`, leaving the configured reserve for report
synthesis/repair. JSON parsing rejects duplicate keys and nonstandard numeric
constants. Schema/policy failures use at most `max_plan_corrections` additional
calls. Provider errors terminate planning with an explicit issue; no new retry
policy is introduced here. Calls use the remaining execution timeout. External
cancellation propagates and cancels the waiting model coroutine.

Successful state has `planning_status="ready"`, a validated plan, and a prioritized
queue. Terminal failure has `planning_status="failed"`, execution issues, an empty
queue, and deferred audit decisions. This status does not assert that the future
analyst has completed the repository investigation or produced a valid report.

## Verification

```bash
uv run pytest tests/project_analysis -q
uv run ruff check src/server/agents/project_analysis tests/project_analysis
```

Tests use scripted models and execute the actual subgraph. They cover multi-project
orientation, library/example candidates, grouped objectives, explicit omissions,
duplicates, fabricated references, prompt/response/candidate limits, bounded
correction, report-call reservation, provider errors, timeout/cancellation,
follow-up provenance, blocker priority, cycles, and insufficient budgets.
