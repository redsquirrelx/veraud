# Simple Project Orientation

`ProjectOrientationAgent` uses LangGraph and the retained repository representation
to provide project type, brief purpose, relevant components, investigation starting
files, and important uncertainties. It does not reconstruct complete flows.

## Run

From `agent-server`:

```powershell
uv run python -m server.run_project_orientation ../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria
uv run python -m server.run_project_orientation ../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria --json
uv run python -m server.run_project_orientation ../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria --smoke
```

`run_project_orientation.py` uses the focused `repository_runner.py` lifecycle for
provider configuration, progress, limits, telemetry, and cleanup. The installed
console entrypoint is `project-orientation`.

The graph is `prepare_context → inspect → tools/validate → finish`, with bounded
inspection loops and at most one correction. There are at most **4 logical model calls**
and **6 tool requests**; lower runner limits are respected. Existing token/time
limits, progress heartbeats, provider cleanup, and usage telemetry still apply.
Provider retry attempts are counted separately and remain budget-bound.
Context fitting reserves room for tool results on the initial turn, reduces
navigation metadata before code, and protects recent source from two distinct files
when available. A compact query/evidence ledger survives history pruning. Source
requests are bounded to approximately 1,400 characters by choosing actual line ranges;
the model sees the actual range and original requested end with explicit truncation.
Full source remains retained and additional ranges can be queried.
No planning or report-synthesis model calls are used.

The orientation JSON itself is snapshot-bound and usable by downstream agents;
those agents must use the same snapshot and verify material claims directly.
`--smoke` tests protocol only and returns unresolved semantic observations.

## Implementation

- `project_orientation/agent.py`: small LangGraph and bounded execution.
- `project_orientation/prompting.py`: measured prompts and source-first context fitting.
- `project_orientation/results.py`: partial recovery and final result assembly.
- `project_orientation/context.py`: compact projection, source-reference validation,
  and preservation of independently valid sections.
- `project_orientation/schemas.py`: small output and action contracts.
- `project_orientation/prompts/`: `system.md`, `investigation.md`, `correction.md`.
  Templates are loaded at runtime and included in reproducibility fingerprints.

The projection uses existing projects, technologies, files, entrypoints, and import
fan-in. It offers a limited set of candidate files with explicit omissions. All
tool access is routed through `RepositoryToolset`; neighboring checkouts and
narrative documentation remain excluded. No snapshot, source, or runtime state
is automatically persisted.

Supported observations require source evidence actually delivered in this run.
Supported component responsibilities must cite a source in their `file_ids`.
Validation establishes access/reference integrity, not semantic correctness.
Hypotheses/unresolved observations require limitations. Fewer than 3–6 components
are acceptable when inspection cannot justify more.

Complete means the bounded orientation has type, purpose, starting points, inspected
source, and no validation/execution issues; it does not mean exhaustive understanding.
Invalid sections are discarded independently, preserving useful partial output.
No valid type, purpose, or component means failed. Provider token totals remain
unknown if an attempt lacks usage; available reported counts remain visible.
Rejected requests emit `context_rejected` with the reason, serialized context sizes,
conservative input estimate, remaining total/objective tokens, and output reserve.
No prompt/source content is printed by this diagnostic.

## Library Use

```python
from server.agents.project_orientation import ProjectOrientationAgent

result = await ProjectOrientationAgent(model).run(tools)
```

Supply fresh snapshot-bound tools per run. The caller owns the model and its clients.
The CLI uses compact tool limits; library callers configure their `ToolLimits`.
See [the shared runtime guide](repository-runtime.md) for tool construction and runner options.

## Initial Verification

The full test suite passed **259 tests**. Orientation checks cover LangGraph routing,
source provenance, documentation exclusion, malformed-section recovery, fixed call
and tool limits, token admission, external cancellation, and the CLI mode.

Initial real Google `gemini-3.1-flash-lite` runs (no retries):

| Case | Contract status | Model calls | Tools | Reported input + output tokens |
| --- | --- | ---: | ---: | ---: |
| Polleria | complete | 2 | 3 | 6,206 + 1,089 = 7,295 |
| PyShop | complete | 3 | 2 | 6,714 + 719 = 7,433 |
| FastAPI | complete | 3 | 3 | 9,448 + 1,589 = 11,037 |

These are small-scope orientation runs, not equivalent-coverage comparisons with
the full analyst. Structural validation passed, but spot checks still found
overstatement: imported stock services in Polleria and routing imports in FastAPI
do not establish their complete implementation behavior. PyShop's new-arrivals
view returns a static response, not a notification mechanism. Prompts were then
clarified to distinguish calls/imports from inspected behavior and to mark likely
interpretations hypothetical. Those refinements do not constitute semantic proof.
Downstream agents must verify material observations against implementation.
