# Focused Architecture Agent

`ProjectArchitectureAgent` interprets the observed architecture from the retained
repository representation and inspected implementation. It explains organization,
the closest pattern, supporting decisions, deviations/tensions, relevant
infrastructure, and a brief summary with scoped uncertainty.

## Run

From `agent-server`:

```powershell
uv run python -m server.run_project_architecture ../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria
uv run python -m server.run_project_architecture ../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria --json
uv run python -m server.run_project_architecture ../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria --smoke
```

The dedicated runner prepares one snapshot, runs orientation, then gives that
orientation and the same snapshot to the architect. Each role has a fresh restricted
tool/evidence ledger. Orientation conclusions are navigation hints; the architect
must retrieve its own source before using a claim as supported.

`--skip-orientation` runs the architect directly over the representation. Shared
runner usage is `server.run_project_analysis ... --architecture`. Architecture
mode is separate from baseline, analyst planning/evaluation, and analyst handoff
modes. The architecture result itself is the snapshot-bound validator handoff.

## LangGraph and Limits

```mermaid
flowchart TD
    START([START]) --> PREPARE[prepare_context]
    PREPARE --> INSPECT[inspect]
    INSPECT -->|Tool requests| TOOLS[tools]
    TOOLS --> INSPECT
    INSPECT -->|Response or malformed output| VALIDATE[validate]
    VALIDATE -->|One correction within budget| INSPECT
    VALIDATE -->|Valid or corrections exhausted| FINISH[finish]
    INSPECT -->|Budget or provider stop| FINISH
    FINISH --> END([END])
```

Only `inspect` calls the model. Initial source inspection uses a tool-only contract;
the full architectural response contract becomes available after source from at
least two files is delivered (or the available file count for a smaller repository).
The model selects the files and ranges. Final validation additionally requires
supported pattern classifications to span different observed responsibilities.
The prompt retains a compact source-evidence ledger even when old excerpts leave
the working context, so citation IDs and actual ranges are not lost. Missing source
can be requested again if interpretation needs it.
Context pruning removes navigation metadata before source and preserves the two
most recent source results. If that irreducible context cannot fit the input
budget, admission stops explicitly instead of silently dropping all source.

The architect has at most **6 logical model calls, 10 tool requests, one correction**.
Orientation has at most four calls/six tools. Lower runner limits are respected by
each stage. Provider retries are separate, bounded attempts. The pipeline shares
the total token admission limit and elapsed-time limit; per-objective token limits
apply independently to orientation and architecture. No model planner, synthesis
stage, follow-up queue, persistence, or validator model is added.

Default token admission limits are inherited from the shared runner: 60,000 total,
6,000 input per call, 20,000 per objective, and 3,000 output per call. Adjust the
architecture objective allowance when calibration warrants it, for example:

```powershell
uv run python -m server.run_project_architecture ../appdata/workspace/563728375-szymon6927-hexagonal-architecture-python --max-objective-tokens 30000 --json
```

## Output and Evidence

The `architecture` object contains:

1. `organization` and `connections`: responsibilities and scoped boundaries.
2. `closest_architecture`: pattern and an assessment, including uncertainty.
3. `supporting_evidence`: implementation decisions supporting the interpretation.
4. `deviations`: observed decisions, inferred pattern expectations, and explanations.
5. `infrastructure`: execution units, communication, or state; `configured` and
   `inspected_use` are separate observations.
6. `explanation` and `uncertainties`: concise architecture description and gaps.

Every architectural claim has statement, scope, status, evidence IDs, and limitations.
Supported claims require source delivered during the architect's investigation.
Supported unit responsibilities cite their own files. Supported connections cite
both responsibilities; supported classifications require multiple files across
at least two observed responsibilities. This checks provenance, not whether the
model's interpretation is semantically sufficient.

The host assembles `citations` from accepted source evidence: evidence ID, file ID,
repository-relative path, actual line range, and content hash. The result includes
snapshot identity, retrieved evidence, inspected files, limitations, execution
issues, usage, and telemetry. These allow a future validator to inspect material
claims directly against the same snapshot without inheriting the conversation.

Mixed/partial styles and no clear pattern are valid interpretations. Names alone
do not establish architectural separation. A mismatch with an inferred style is
not automatically a defect. Configured infrastructure does not prove production
deployment, and declared technology does not establish runtime usage.

`complete` means the bounded report has organization, classification, explanation,
multi-file inspection, and no execution/validation failures. It does not mean global
compliance or semantic acceptance. Invalid sections are discarded independently;
useful surviving sections produce `partial`. No substantive report means `failed`.

`usage` and `telemetry` concern the architect only. `orientation_result` contains
the earlier stage; `pipeline_usage` shows combined reported consumption. Complete
provider totals remain null if any attempt lacks usage; known reported counts
remain available separately from conservative token estimates.

## Files and Library API

The implementation lives under `src/server/agents/project_architecture/`:
`agent.py`, `context.py`, `schemas.py`, and `smoke.py`. Prompts are runtime-loaded
from `prompts/system.md`, `architecture_criteria.md`, `investigation.md`, and
`correction.md`; they participate in reproducibility fingerprints.

```python
from server.agents.project_architecture import ProjectArchitectureAgent

result = await ProjectArchitectureAgent(model).run(architecture_tools, orientation_result)
```

Use fresh snapshot-bound tools; the caller owns model resources. Passing orientation
from another snapshot fails before a model call. Tools retain checkout isolation
and narrative documentation exclusions, including indirect evidence retrieval.
The installed CLI entrypoint is `project-architecture`.

## Verification and Initial Calibration

`uv run --no-sync pytest -q`: **271 tests passed**. Targeted Ruff checks passed.
Architect checks cover multi-file classification/connection references, exact source
citations, snapshot mismatch before model submission, independent orientation evidence,
configuration versus implementation, docs/neighbor access, bounded calls/tools,
token stops, external cancellation, partial recovery, and the dedicated runner.

Initial real Google `gemini-3.1-flash-lite` calibration used a 30,000-token objective
allowance, 150 seconds, and no provider retries:

| Case/run | Status | Architect calls/tools | Architect reported tokens | Combined reported tokens |
| --- | --- | --- | ---: | ---: |
| Hexagonal Python, with orientation | partial | 5 / 10 | 18,954 | 26,141 |
| FastAPI, with orientation | partial | 3 / 4 | 12,845 | 20,165 |
| Polleria, with orientation | failed | 0 / 0 | No architect request | Unknown |
| Hexagonal Python, later direct run | partial | 5 / 10 | 19,972 | 19,972 |

The Polleria run stopped after a provider failure in orientation; no architect
request was sent and the combined complete usage was unknown. Earlier diagnostics
also revealed that the model tried to classify from guidance without source; the
tool-only initial contract now requires source inspection before classification.

The later Hexagonal Python run retained domain/application/infrastructure organization
and a scoped ports-and-adapters classification, citing `client.py`, `client_service.py`,
and `dropbox_clients_exporter.py`. Invalid citation-bearing sections were rejected,
so the report remained partial. A compact evidence ledger was added after the first
calibrations to retain citation identity as working context is pruned.

Source spot checks show both useful observations and remaining semantic overstatement:
`ClientService` receives repository/exporter abstractions and calls the repository;
`DropboxClientsExporter` implements the exporter abstraction and uploads reports.
Those files support the scoped separation, but do not establish global strict
hexagonal compliance or prove persistence behavior merely from an exporter. The
FastAPI run also compared a framework integration against an unrelated Clean
Architecture expectation; the prompt was clarified to compare deviations with the
selected style. No complete semantic acceptance or stable repeated-run quality is
claimed from these calibration runs. The future validator should review such
material claims and expand inspection only where evidence is insufficient.
Final prompt/context refinements compacted repeated instructions and source envelopes
and protected recent multi-file source from pruning. Direct offline Hexagonal Python
verification then completed with a partial protocol result in two calls/two tools;
these refinements are not a new scored real-model quality evaluation.
