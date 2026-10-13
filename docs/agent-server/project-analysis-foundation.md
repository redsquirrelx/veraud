# Project Analysis Foundation (Phase 1)

The additive `server.agents.project_analysis` package defines contracts and
in-memory runtime dependencies for the planned project analysis LangGraph.
See [the workflow and runner guide](project-analysis-runner.md) for the complete agent.

## Available Foundation

- Frozen, strict Pydantic contracts for input, budgets, candidates, objectives,
  planning decisions, retrieved evidence, claims, components, flows, integrations,
  test observations, reports, execution results, and architecture handoff.
- `ProjectAnalysisState`: a typed LangGraph state with explicit channel reducers.
- `ProjectAnalysisContext`: a per-run snapshot, internal query service,
  read-only reference indexes, monotonic start time, and state initialization.
- Deterministic snapshot binding, typed reference validation, source hash/range
  validation, and report/completion consistency checks.

The existing `BaseAgent` uses input/output Pydantic models and a caller-supplied
model. Existing model adapters expose asynchronous text `generate` methods;
tool calling and structured results will require an integration layer in later
phases. Existing tracing wrappers and benchmark client cleanup were inspected.
This foundation allocates no provider clients or tracing callbacks. Future model
integration must define ownership and reuse compatible cleanup/retry behavior.

## Use

```python
from server.agents.project_analysis import (
    ProjectAnalysisContext,
    ProjectAnalysisInput,
)
from server.services.repository_analysis import RepositoryAnalysisService

snapshot = RepositoryAnalysisService().analyze_sync("path/to/repository")
context = ProjectAnalysisContext(
    snapshot=snapshot,
    input=ProjectAnalysisInput(snapshot_hash=snapshot.repository.snapshot_hash),
)
initial_state = context.initial_state()
```

Use `ProjectAnalysisState` with `StateGraph(...,
context_schema=ProjectAnalysisContext)` and inject the context at invocation.
Snapshot/source content stays in runtime context rather than graph messages.
The context's raw query service is an internal dependency. Phase 2 now provides
[documentation-filtered, workspace-bound tools](project-analysis-tools.md).
Use their `initial_state()` method for the policy-filtered graph overview.

## State Semantics

- Accepted candidates, decisions, retrieved evidence, findings, questions, and
  execution issues accumulate by ID. Exact replay is idempotent; conflicting
  rewrites raise an error. Correct drafts before accepting them.
- Queues, active target, drafts, validation errors, correction counters, and
  cumulative budget usage replace their previous value. A sequential scheduler
  must own updates to queue and usage channels.
- Messages use LangGraph `add_messages`, including ID-based replacement and
  explicit `RemoveMessage` operations when switching investigation targets.
- Each `initial_state()` creates independent mutable message lists; record
  collections and contracts are immutable.

## Validation Boundaries

`context.validate_plan(...)` checks snapshot seed/project references, plan size,
follow-up origin references, and accepted/grouped decision references.

`context.validate_report(...)` checks snapshot identity, accepted plan references,
typed snapshot/local entity references, and retrieval content hashes/ranges.
Report coverage must match the accepted plan and its outcome ledger.

`context.validate_result(...)` validates an execution result against the snapshot.
Complete results require a nonempty completed plan. Partial results require an
explicit incomplete scope or execution reason. Failed results require execution
issues and cannot carry a valid report. Open questions can remain in a complete
run: completion means finishing the planned investigation scope.

`ArchitectureAnalysisInput.from_result(...)` accepts valid complete/partial
results and rejects failures. Validate the handoff with the receiving
`context.validate_architecture_input(...)` to verify it uses the same snapshot.

Reports contain the accepted investigation plan and compact outcomes for
planning auditability and follow-up provenance. Those records do not duplicate
retrieved source content.

These checks establish structural integrity, not whether evidence semantically
supports a statement. Phase 2 implements tool access policy, actual retrieval
registration, and tool/content/time budget checks. Investigation planning/routing,
model budgets, and semantic evaluation belong to subsequent phases.

## Checks

```bash
uv run pytest tests/project_analysis -q
uv run ruff check src/server/agents/project_analysis tests/project_analysis
```
