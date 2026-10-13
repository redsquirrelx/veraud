# Project Analysis Context and Usage Telemetry

The first simplification step instruments the existing workflow. Planning,
investigation, correction, synthesis, and repair behavior remain in place.

## Run with uv

From `agent-server`:

```powershell
uv run python -m server.run_project_analysis ..\appdata\workspace\1373928788-Cesar-Sanchez-sof-Polleria
uv run python -m server.run_project_analysis ..\appdata\workspace\1373928788-Cesar-Sanchez-sof-Polleria --json
```

Each `model_call_started` event includes stage, correction flag, prompt characters,
estimated input tokens, estimator label, and context composition. The readable
result prints stage totals and repeated tool request counts. JSON includes
`telemetry` and `run_metadata`, including failed runs. Planning-only output and
workspace evaluation expose the same measurements. No files are written automatically.

## Exact Character Composition

Prompt builders preserve the serialized text and attach a disjoint character
partition. Category counts sum to `prompt_characters` for every call.

| Category | Meaning |
| --- | --- |
| `instructions` | Behavioral instructions |
| `contracts` | Output JSON schemas and tool argument schemas |
| `metadata` | Candidates, seeds, objectives, repository summary, counters |
| `source` | Source/search text serialized within retained tool messages |
| `history` | Prior findings, model messages, tool envelopes and metadata |
| `feedback` | Validation and correction errors |
| `framing` | Section separators and stage labels |

These are serialized prompt lengths, including JSON escaping, not raw source
lengths. Source is counted each time it occurs in a prompt. Comments/docstrings
contribute to source size without independently proving behavior.

Stage character totals describe logical prompts. Attempts are separate; retries
can submit the same prompt again. Estimated stage input tokens include repeated
attempts. Provider tokens are not allocated proportionally across character categories.

## Estimates Versus Reported Usage

The local estimate is `ceil(prompt_characters / 4)`, labeled
`ceil_characters_divided_by_4_not_provider_tokenization`. It is a diagnostic
heuristic, not provider tokenization, billing data, or a budget guarantee.

Stage records separate:

- `reported_input_tokens` / `reported_output_tokens`: sums of available counts.
- `input_tokens` / `output_tokens`: complete totals, or null when incomplete.
- `unknown_usage_attempts`: attempts without both usage counts.
- `estimated_input_tokens`: independent local estimates across attempts.

If a failed attempt has unknown usage and a retry succeeds, the reported counts
are retained but the run total is not presented as complete. Unknown usage is
never replaced with an estimate or interpreted as zero.

The library's text-model protocol does not supply usage metadata. Its transparent
observer records composition, stage, timing, and response length, with unknown
measured tokens. The runner's gateway additionally observes provider usage and
explicit retries. Internal SDK retries are not individually observed.

## Repeated Requests and Corrections

Charged tool requests, including controlled errors, record SHA-256 signatures of
tool name and schema-normalized arguments. Default arguments and key order do not
hide exact repeats. Records contain IDs, tool names, signatures, repeat flags,
status, and timing; they contain no arguments, source, or response bodies.

Rejected replay IDs and exhausted-budget attempts are not additional charged
requests. Differently spelled equivalent paths are not semantic deduplication.
Correction calls are labeled from supplied feedback; report repair is a separate
`repair` stage. Instrumentation does not change correction limits or accept invalid facts.

## Reproducibility and Privacy

`run_metadata` records snapshot hash, repository commit, provider/model,
temperature/output limit, investigation budgets, extraction bounds, pacing/retries,
and an implementation fingerprint of the analyst, repository-analysis modules,
and runner. This is not a complete environment/dependency fingerprint.

Telemetry does not automatically retain prompts, source, credentials, or provider
response bodies. The existing snapshot/history still retain their normal in-memory
content. Explicitly enabled tracing is a separate feature. The architecture
handoff contract remains focused on the report and snapshot.

## Polleria Baseline Supplied Before Instrumentation

| Field | Observed value |
| --- | --- |
| Repository | `1373928788-Cesar-Sanchez-sof-Polleria` |
| Provider/model | `google` / `gemini-3.1-flash-lite` |
| Snapshot files / accessible files | 295 / 257 |
| Planned / started investigations | 3 / 3 |
| Model calls / provider attempts | 17 / 17 |
| Tool calls / provider retries | 12 / 0 |
| Input / output / total tokens | 208,266 / 10,142 / 218,408 |
| Retrieved response characters | 50,961 |
| Agent elapsed time | Approximately 40.34 seconds |
| Final status | `failed` |
| Maximum investigations / model calls / tools | 12 / 40 / 100 |
| Execution timeout / per-target turns | 600 seconds / 8 |
| Extraction file/depth limits | 5,000 / 30 |
| Snapshot hash / commit / temperature / output limit | Not present in supplied log |

| Stage | Calls | Reported input tokens |
| --- | ---: | ---: |
| Planning | 2 | 46,587 |
| Investigation, including corrections | 12 | 156,990 |
| Synthesis and repair | 3 | 4,689 |

Historical context-category counts cannot be reconstructed from that log. New
runs provide them, along with explicit snapshot/configuration metadata. Compare
quality and scope alongside consumption; changed plans or snapshots are not a
controlled token comparison. Real-provider baseline runs remain explicit.

## Instrumentation Verification

An explicit offline protocol run on Polleria with three investigation slots
recorded 10 scripted calls and five tools, including two repeated requests.
Across eight investigation turns, serialized contracts accounted for 146,688
characters, history for 37,338, and source for 730. Planning candidate/entity
metadata accounted for 55,339 characters. These are protocol diagnostics, not
real-provider token measurements or semantic-quality scores.

Tests verify exact JSON serialization and nonoverlapping escaped-source counts,
stage aggregation, incomplete usage after retries, content-free telemetry,
normalized repeated requests, runner metadata, and the standalone text-model path.
