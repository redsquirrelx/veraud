# Shared Repository Runtime

`server.agents.repository_runtime` provides only the execution primitives used by
project orientation, project architecture, and semantic validation. It has no dependency on any role.
The deterministic snapshot/query service remains in `services/repository_analysis`.

## Code map

| Module | Responsibility |
| --- | --- |
| `schemas.py` | Frozen execution budget, usage, evidence, request, and issue contracts |
| `context.py` | Snapshot identity and per-run elapsed time |
| `access.py` | Selected-checkout isolation and exclusion of narrative documentation |
| `tools.py` | Seven bounded query adapters, retrieval provenance, caching, and tool measurements |
| `model_runtime.py` | Provider text normalization, retry/pacing, usage, and cleanup |
| `telemetry.py` | Content-free serialized prompt and provider/tool measurements |
| `token_budget.py` | Conservative request admission and token accounting |
| `working_context.py` | Source-first fitting, bounded source ranges, and rejection diagnostics |
| `responses.py` | Strict bounded JSON parsing, array repair, and validation feedback |
| `results.py` | Role-local usage and telemetry assembly |

Each role keeps its own prompts, report contracts, graph, projection, validation,
and partial recovery. `prompting.py` builds context; `results.py` assembles the final
report. No generic agent framework or model-driven planner is involved.
The [semantic validator](project-semantic-validation.md) additionally uses role-local
usage accounting for initial review and revalidation, with independent source ledgers.

## Library use

```python
from server.agents.repository_runtime import (
    ExecutionBudget, RepositoryContext, RepositoryInput, RepositoryToolset,
)
from server.agents.project_orientation import ProjectOrientationAgent
from server.agents.project_architecture import ProjectArchitectureAgent

def fresh_tools(snapshot, workspace_root):
    return RepositoryToolset(
        RepositoryContext(
            snapshot=snapshot,
            input=RepositoryInput(
                snapshot_hash=snapshot.repository.snapshot_hash,
                budget=ExecutionBudget(max_tokens_per_objective=40_000),
            ),
        ),
        workspace_root=workspace_root,
    )

orientation = await ProjectOrientationAgent(model).run(fresh_tools(snapshot, workspace_root))
architecture = await ProjectArchitectureAgent(model).run(
    fresh_tools(snapshot, workspace_root), orientation,
)
```

The caller owns the model and its clients. Both roles reuse the same retained
snapshot with separate tool/evidence ledgers. The architect independently retrieves
source supporting material claims. Snapshots and runtime state remain in memory.

## Runners

Use `server.run_project_orientation` or `server.run_project_architecture`, or the
installed `project-orientation` / `project-architecture` commands. Each requires a
checkout directly inside `--workspace-root` (default: `appdata/workspace`).
`repository_runner.py` owns the common CLI lifecycle and `repository_progress.py`
provides flushed stderr events and cancellable wait heartbeats.

Common options:
- `--smoke`, `--json`, `--quiet`, `--trace`, `--progress-interval`.
- `--provider`, `--model`, `--api-key`, `--temperature`, `--max-tokens`.
- `--max-total-tokens`, `--max-input-tokens`, `--max-objective-tokens`.
- `--max-model-calls`, `--max-tool-calls`, `--max-retrieved-characters`, `--timeout`.
- `--request-interval`, `--max-retries`, `--retry-backoff`, `--max-files`, `--max-depth`.

Architecture additionally accepts `--skip-orientation` and
`--strict-architecture-budgets`. Architecture token/context targets are advisory
by default; orientation admission is strict. Provider retries, call/tool counts,
elapsed time, and provider output limits are bounded. Pipeline usage includes both
roles; architecture usage filters provider measurements to its own objective.
Provider usage stays unknown when an attempt omits token counts.

## Checks

```powershell
uv run pytest tests/repository_runtime tests/project_orientation tests/project_architecture -q
uv run ruff check src/server/agents/repository_runtime src/server/agents/project_orientation src/server/agents/project_architecture src/server/repository_runner.py src/server/repository_progress.py
```

These checks cover access isolation, source ranges, provenance, retries,
cancellation, context fitting, recovery, classification references, application
coverage, and runner handoff. Offline smoke checks validate the protocol, not the
semantic accuracy of model conclusions.

After the runtime extraction and agent cleanup, the full `uv run pytest -q` suite
passed. Targeted Ruff and `git diff --check` passed.

Compared with the last committed version, the focused agent/runtime/runner source
and prompts decreased from **9,479 to 5,243 lines** (44.7%). This comparison includes
the subsequent architecture improvements and counts newly added files; it excludes
tests, documentation, and the retained deterministic snapshot service.
