# Project Analysis Simplification: Implementation and Measurements

## Implemented phases

1. **Measurement:** exact serialized context partitions, provider usage completeness,
   stage/correction/repeated-query telemetry, and reproducibility fingerprints.
   Ordinary strings are passed to the Google SDK; measurement metadata stays local.
2. **Mechanical stages:** default deterministic scope selection and report assembly;
   the standalone planner and retained baseline analyst remain available. Candidate
   priorities, import fan-in, source diversity, and project coverage are heuristics.
3. **Compact tools:** small model envelopes, bounded source ranges and pagination,
   actionable argument errors, query reuse, and independent delivered provenance.
   Dependency constraints, resolved versions, scope, and markers remain distinct.
4. **Working context/contracts:** bounded recent unique tool results, query ledger,
   relevant prior components, explicit omissions, objective-sized type grammar,
   and bounded field-level errors. Singleton object arrays are normalized without
   inventing facts. Independently valid records survive malformed siblings and
   later provider/budget failures. Repeated unchanged invalid submissions stop.
5. **Token limits:** per-run, per-input, per-objective, and output limits; conservative
   pre-request admission including retries; separate reported and estimated usage;
   deterministic finalization on exhaustion without reporting model reserves.
6. **Compact handoff:** snapshot-bound functional facts, relevant provenance,
   objectives/outcomes, deferred-category counts, coverage, and unanswered questions.
   The receiving architect still verifies material claims directly using source.
7. **Evaluation:** two real-model repetitions for each pinned case, final offline
   verification, additional Polleria calibration, and source spot checks. Evaluation
   found incomplete coverage and semantic insufficiency; quality acceptance is not met.

## Polleria calibration

Model: Google `gemini-3.1-flash-lite`. Retained snapshot:
`eebba32dee7669f37f1507f891350c2a386a650598078880d9877dff94498749`.

| Metric | Supplied baseline | Simplified measured run |
| --- | ---: | ---: |
| Status | failed | partial |
| Investigations started | 3 | 4 |
| Logical model calls | 17 | 9 |
| Tool calls | 12 | 9 |
| Provider input tokens | 208,266 | 30,531 |
| Provider output tokens | 10,142 | 3,140 |
| Provider total tokens | 218,408 | 33,671 |
| Agent time (seconds) | about 40.34 | 38.44 |

This run used four targets, a 40,000 total-token admission limit, 20,000 tokens per
objective, 6,000 input/3,000 output tokens per call, 180 seconds, and no retries.
The measured reduction is **84.6%** relative to the supplied baseline. This is an
unpaired observed comparison with different scope/budget policies, not evidence
of equivalent coverage or a guaranteed reduction. Both results are incomplete.

A subsequent run with a 60,000 total/25,000 objective budget and one retry produced
a partial report with project identification and three component records, but no
accepted flows. It made 10 logical calls/11 provider attempts and five tool calls;
HTTP 429 interrupted correction. Available reported usage was 30,213 input plus
5,152 output tokens. Two attempts had unknown usage, so complete provider totals
remain **null**. Operational accounting was 52,743, including 17,378 estimated
tokens; this is not a measured provider total.

Another calibration encountered HTTP 503 and likewise retained earlier findings.
The final response examples were clarified after these runs. Singleton-array
normalization was tested and exercised in the last calibration; nested claim
examples and unchanged-response stopping were verified by automated checks.

## Tool projection measurement

For the same 20-file Polleria page, the baseline serialized envelope was 14,697
characters. The compact model view was 6,666 characters (**54.6% smaller**), with
the full compact provenance envelope retained internally at 11,557 characters.
These are serialized-character measurements, not provider token counts.

## Six-case real-provider evaluation

```powershell
uv run --no-sync python -m server.run_project_analysis --evaluate-workspace --repeat 2 --provider google --model gemini-3.1-flash-lite --max-investigations 4 --max-total-tokens 60000 --max-objective-tokens 25000 --timeout 180 --max-retries 0 --json --quiet
```

Evaluation ran during implementation, before the final singleton-array and nested
claim-shape refinements. Each result includes its implementation fingerprint and
settings. It therefore diagnoses the reduced workflow rather than establishing
final-version semantic acceptance.

| Case | Two outcomes | Location-overlap proxy | Actual total when complete usage exists |
| --- | --- | --- | --- |
| PyShop | failed, partial | 0%, 33% | second: 46,827 |
| Hexagonal Python | partial, failed | 33%, 0% | unknown |
| Mario | failed, partial | 0%, 100% | second: 46,367 |
| GitFolio | partial, failed | 33%, 0% | unknown |
| Hexagonal TypeScript | failed, failed | 0%, 0% | unknown |
| FastAPI | partial, partial | 67%, 67% | 53,390 each |

Across 12 runs: six partial, six failed, 74 logical model calls, and 42 tool calls.
The six runs with claims had structurally valid citations at 1.0. **No run produced
accepted main flows.** All six failed runs encountered HTTP 429 or 503; two partial
runs also encountered 429. Model response-shape errors affected all partial runs.
FastAPI reached token admission limits. FastAPI statement/status fingerprints were
identical; other meaningful repeated-case stability was not established. Identical
empty failed outputs are not semantic stability.

## Source spot checks and quality conclusion

These checks are qualitative diagnostics, not a complete scored semantic review:

- Mario's Core initialization and input/update/render loop are directly visible
  in `Next/Core.py:18-48`, supporting the corresponding responsibility.
- PyShop's claimed product-request responsibility cited only `requirements.txt`.
  That file proves a declared Django dependency, not product view behavior.
- Hexagonal Python's `src/app.py` proves router composition and error handlers;
  its architecture title does not prove repository-wide hexagonal separation.
- FastAPI's `fastapi/__init__.py` proves public exports, not dependency-injection
  or request-handling implementation merely because those names are imported.
- Polleria's first accounts-page claim included search/filter behavior while
  citing only lines 1-50. These lines show state and account loading; filter
  implementation begins later. Citation existence did not establish sufficiency.

**Consumption and preservation improve; equivalent or better functional quality
has not been established.** Reports now survive unrelated malformed records and
provider failures, but incomplete flows and overstated supported claims remain.

For subsequent acceptance, require at least two provider-available runs per case,
zero materially unsupported reviewed `supported` claims, correct coverage of every
curated in-scope reference responsibility/flow, and explicit out-of-scope omissions.
Compare against a paired baseline with the same model, snapshot, and scope; measure
Polleria at at most 60,000 provider-reported tokens while retaining those in-scope
facts. These proposed gates are not met by the current evaluations.

## Final verification

`uv run --no-sync pytest -q`: **252 passed**. Targeted Ruff checks passed for
the project-analysis package, runner, and tests.

Final offline six-case evaluation: 12 partial protocol results, stable fingerprints
for all six cases, 48 scripted model calls and 26 tool calls. This confirms protocol
and citation behavior, not model semantics. Automated checks cover deterministic
assembly, evidence integrity, malformed-record salvage, compact handoff, singleton
normalization, token stops, retry admission, documentation exclusion, SDK wire
equivalence, cancellation, and baseline compatibility.

Explicit evaluation exports were placed in the approved temporary directory;
the runner still performs no automatic persistence. No current-price billing
claim is made without supplied prices and complete provider usage.
