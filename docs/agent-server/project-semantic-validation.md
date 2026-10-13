# Semantic Architecture Validation

`ProjectSemanticValidationAgent` independently checks whether architectural claims
are justified by retained implementation, their literal wording, scope, and certainty.
Reference validation confirms that a citation exists; semantic review evaluates what
the cited source actually demonstrates.

## Flow and ownership

```text
retained snapshot -> orientation -> architecture -> semantic validation
                                            ^              |
                                            +-- one return-+
```

Each role has a fresh tool/evidence ledger over the same snapshot. Architect citations
are navigation hints: decisive validator findings must cite source independently
delivered to the validator. The original architectural result is preserved exactly
as a typed input. Proposed corrections are separate, source-backed records and are
never automatically applied to the report.
For claims with original source hints, at least one cited range must also overlap
an independently inspected source range before any finding is accepted. The host
rejects closing a claim using unrelated inspected files.

## Run

From `agent-server`, independently review an architecture JSON export:

```powershell
uv run python -m server.run_project_architecture ../appdata/workspace/316988921-Sairyss-domain-driven-hexagon --json > architecture.json
uv run python -m server.run_project_semantic_validation ../appdata/workspace/316988921-Sairyss-domain-driven-hexagon --report architecture.json --json
```

The installed entrypoint is `project-semantic-validation`. The report loader accepts
UTF-8 or BOM-marked UTF-16 (including Windows PowerShell exports), rejects duplicate
JSON keys/nonstandard constants, and reads at most 2 MB. It accepts the architecture
runner envelope and normalizes the retired zero-valued analyst usage counter in older
exports. The report snapshot and source hashes must match the retained checkout.

To include review in an architecture run:

```powershell
uv run python -m server.run_project_architecture ../appdata/workspace/316988921-Sairyss-domain-driven-hexagon --validate-semantics --json
uv run python -m server.run_project_architecture ../appdata/workspace/316988921-Sairyss-domain-driven-hexagon --validate-semantics --no-semantic-return --json
```

`--validate-semantics` allows one return to the architect when accepted review findings
request missing evidence. The architect receives concrete target pointers, original
claim wording, reasons, and investigation questions, retrieves its own evidence,
and produces a separate revised result. The validator then independently revalidates
that result. Remaining requests are preserved; no second return is scheduled.
Decisive corrections alone do not trigger a return. `--no-semantic-return` performs
only the first review.

The top-level architectural JSON output remains the original result. `semantic_validation`
contains `original_architecture`, optional `revised_architecture`, `validations`, and
`return_count`. A failed revision or exhausted revalidation budget remains visible.
CLI exit code zero means a usable execution result, not semantic acceptance; consumers
must inspect the semantic verdict and coverage.

The human-readable CLI summary explicitly labels the displayed report as ORIGINAL
or REVISED. It displays the revised report when one was produced, with its own
citations and usage, and falls back to the original if revision produced no report.
Architecture generation status is separate from semantic review/revalidation status
and final acceptance. Each displayed claim labels architect certainty separately
from its semantic verdict (`not reviewed` for pending claims). Review coverage,
pending pointers, execution issues, missing-evidence questions, and proposed
corrections are printed explicitly. Proposed corrections are not automatically
applied. A revision without revalidation is identified as such; the earlier review
is never presented as validation of the new report.

## Findings and coverage

Every review target is a JSON pointer relative to the architectural report, bound to
a canonical SHA-256 `report_hash`. Deterministic priority order is classification,
responsibilities, connections, explanation, contrast, nested dependency/runtime links,
supporting decisions, deviations, and infrastructure. This includes the classification's
non-linear `observed_dependencies` and `observed_paths`.

| Finding verdict | Meaning |
| --- | --- |
| `supported` | Source justifies the exact wording, scope, and declared certainty |
| `overstated` | There is a basis, but wording, scope, or certainty exceeds it |
| `contradicted` | Inspected implementation positively contradicts the statement |
| `insufficient_evidence` | The inspection cannot decide; an actionable question is required |

Each finding has `target_id`, an exact `checked_statement` copy, `reason`, a mandatory `counterevidence_check`, independent
`evidence_ids`, optional `correction`, and optional `missing_evidence`. Corrections
preserve scope/certainty and cite validator evidence. Questions can name accessible
technical paths; narrative documents and neighboring checkouts remain excluded.
The host rejects findings whose copied statement differs from the target's original
text, preventing silent review of a different assertion under the same pointer.

Review the literal statement, including exclusivity words such as ONLY and NEVER.
Optional [architecture diagrams](architecture-diagrams.md) reuse existing claims and
add derived review targets for authored view scope, grouping, and typed relations.
The compact model composition runs before review; it does not load the main
investigation turns with the diagram contract. Pending
diagram interpretations prevent full review acceptance just like other pending claims.
For example, depending on a repository port may support inversion while the assertion
that a use case imports *only* that port is contradicted by other imports. Framework
dependencies do not inherently invalidate a local hexagonal pattern. Configuration
does not demonstrate that production actually executes the configured deployment.

The host derives the overall verdict:
- `revisions_needed`: at least one accepted finding is overstated or contradicted.
- `needs_evidence`: no decisive rejection, but at least one accepted finding is insufficient.
- `accepted`: every present claim was reviewed and supported, with no execution/validation issues.
- `inconclusive`: incomplete review without a decisive rejection or evidence request.

`pending_target_ids` includes both unselected claims and selected claims whose findings
were absent/rejected. They prevent complete review and acceptance. A `complete` review
can still need revisions/evidence: completion describes review coverage, not correctness.
Accepting the claims in a partial architectural report does not upgrade its original
completion status or prove repository-wide coverage. Supporting a calibrated hypothesis
does not upgrade that hypothesis to a supported architectural classification.

## Investigation and budgets

LangGraph: `prepare -> inspect -> tools/validate -> finish`. The first prompt offers a
tool-only contract when source exists and tools remain, including later batches whose
cited ranges have not yet been independently inspected. Claims are reviewed in batches
of at most four; prompt fitting can shrink the active batch without losing claim text.
Tool metadata is reduced before source, recent distinct excerpts are protected, and an
independent evidence ledger survives pruning. Valid findings survive malformed peers,
provider failures, and later budget stops. A no-progress format failure gets one repair.

Defaults: **8 model calls, 16 tools, 18 selected claims**, 24,000 prompt characters,
up to 2,400 characters per excerpt. Runner defaults are 10,000 input tokens/call,
40,000 tokens/objective, 80,000 total, 3,000 output tokens/call. Use
`--max-review-claims`, existing token/call/tool limits, pacing/retry options, and timeout
to configure a run. These logical role limits are separate from provider retry attempts.

The first semantic review uses advisory token budgets in both CLI modes: input,
objective, and total token estimates emit `budget_advisory` events instead of
blocking its requests or provider retries. This applies to the entire initial
review, not just its first model call. Revalidation after an architectural return
still uses strict token admission. Calls, tools, elapsed deadlines, provider output
limits, and the prompt character bound remain enforced. Library callers can opt in
with `run(..., soft_token_budgets=True)`; the direct library default remains strict.
The integrated pipeline shares a provider ledger,
total token admission target, and elapsed deadline. Orientation, architecture,
validation, architecture revision, and revalidation have distinct objective identities,
so exported role usage does not double-count earlier stages. Architecture token targets
remain advisory; if earlier stages exhaust the shared target, later strict revalidation
stops with an explicit partial/failed result. Smoke cycles have unknown provider usage
and may need a larger total allowance because conservative estimates include every call.

Progress events, wait heartbeats, content-free measurements, client cleanup, and
external cancellation follow the [shared runtime](repository-runtime.md).

## Library API and code map

```python
from server.agents.project_semantic_validation import ProjectSemanticValidationAgent

review = await ProjectSemanticValidationAgent(model).run(fresh_tools, architecture_result)
```

`validate_architecture_pipeline` in `server.pipelines.semantic_validation` accepts a
validator, optional architect, and a `fresh_tools` factory bound to the same retained
snapshot and remaining deadline. The caller owns clients and provider lifecycle.
The earlier `server.semantic_validation_pipeline` import remains compatible.
For the full orientation-to-review flow, use
[`ProjectArchitecturePipeline`](project-architecture-pipeline.md). The architecture
CLI uses that same pipeline instead of maintaining a separate orchestration path.

- `agent.py`: typed state, LangGraph, bounded tool/provider turns, and partial recovery.
- `context.py`: input identity, deterministic targets, evidence validation, and finding salvage.
- `prompting.py`: batch/context fitting and measured external prompts.
- `schemas.py`: contracts and structural coverage invariants.
- `results.py`: host-derived verdict, pending targets, independent citations, and role usage.
- `prompts/`: literal claim review and investigation instructions.
- `smoke.py`: offline protocol model; it never establishes semantic acceptance.

## Verification and calibration

The full `uv run pytest -q` suite passed **276 tests** after implementation.
Targeted Ruff and `git diff --check` passed. Tests include independent citation
provenance, exact statement identity, cited-range admission, original-report
preservation, partial recovery, budgets, cancellation, and single-return history.

Run `uv run pytest tests/project_semantic_validation -q` for independent provenance,
all verdicts, partial coverage, selection, salvage, snapshot/ledger mismatch, strict
admission, external cancellation, provider failure, unsafe evidence requests, the
single-return coordinator, and both runner paths.

Real-model calibration uses the pinned Python and TypeScript hexagonal examples and
controlled report variants. These are model judgments with human spot checks, not a
validated semantic-accuracy score. Initial calibration exposed a false acceptance of
an exclusive-import assertion; literal counterevidence checks were then made mandatory.
The reproducible corpus in `server.benchmark.semantic_cases` covers six authored cases:
correct delegation, invented SMTP behavior, reversed dependency direction, a local
pattern overgeneralized to the repository, an unknown production environment value,
and configuration presented as live deployment. Initial runs also exposed an incorrect
production-readiness critique of a claim about adapter selection; the prompt and
source-range admission were tightened to keep those propositions separate.
Repeated-run stability, false-positive rates, and broad accuracy beyond this small
controlled corpus remain unestablished. Review pending coverage, counterevidence checks, and proposed
corrections before interpreting an `accepted` result as reliable architectural advice.

Observed Google `gemini-3.1-flash-lite` calibration:
- Python hexagonal report: 10 claims reviewed, 4 calls/4 tools, initial `accepted` review.
- TypeScript report after literal checks: 11 claims reviewed, 4 calls/4 tools,
  `revisions_needed` for the contrast phrase "domain layer ... imports only the port".
  The local inversion assessment remained supported. Known reported usage was 23,685
  tokens; one 503 attempt had unknown usage. This run used a 60,000-token objective allowance.
- Controlled six-case fixture: initial runs caught invented SMTP behavior, reversed
  dependency direction, and unsupported global scope, but exposed runtime/configuration
  interpretation errors. Source-range admission then forced inspection of bootstrap and
  compose before closure. The latest full run correctly left the production environment
  undecidable, but misattributed an adapter mismatch to the deployment assertion. Exact
  statement copying and explicit cross-claim isolation were added afterward; their
  structural enforcement is tested, but semantic elimination of that error is not yet
  established. These observations are not a general semantic-accuracy score.

Calibration JSON artifacts are stored in the local OpenCode temporary directory:
`semantic-hex-python-full-live.json`, `semantic-hex-ts-final-live.json`, and
`semantic-six-cases-source-admission-live.json`. They preserve earlier schema versions
and are historical measurements, not current-schema fixtures.
