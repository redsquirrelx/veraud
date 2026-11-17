# TestabilityProbeAgent

Generates portable, executable verification suites from testability-investigation
findings (`TestIsolationAgent` / `TestControllabilityAgent`). The agent is a
small coding agent: it interprets each finding with an LLM, consults the real
code, writes pytest modules, runs them in a disposable workspace, classifies
what they mean for the denounced condition, repairs technical failures within a
budget, and exports a `.tallercito/` ZIP that re-executes the suite on later
commits of the same repository without any LLM.

It generates pytest modules for Python findings and executable Vitest (`npx vitest run`)
or `node --test` suites for TypeScript/JavaScript findings. Type-check-compatible
TSX imports run against the audited project's dependencies (and a pinned
`vitest`/`typescript`/`react`/`jsdom` harness) installed only inside the disposable
verification copy. External repository state is never trusted, and the
audited checkout is never modified — dependencies are installed with
`--ignore-scripts` inside the disposable copy and, by default, may download them.

It is a **code-generating verifier, never a corrector**: it never modifies the
audited repository and never re-audits.

## Lane detection

Per finding, the agent classifies the target components by file extension:

- `.py` → pytest lane (existing behavior, unchanged for Python projects).
- `.ts`/`.tsx`/`.mts`/`.cts` → Vitest lane, TypeScript compiler API for structural checks.
- `.js`/`.mjs`/`.cjs` → Vitest or native `node --test` lane.
- mixed components → the language is chosen from the first component; TS and
  JavaScript findings in a Python repo use Vitest.

Vitest/`node:test` tests behave identically to pytest: they must FAIL at the
violating commit (AssertionError for missing seams; or `throw` with
`NOT_VERIFIABLE: reason` for honest "cannot verify") and PASS at a corrected
variant. The oracle absent-not-present rule applies to both lanes.

## Layout

`src/server/agents/testability_probe/`

| Module | Role |
|---|---|
| `agent.py` | Facade. Requires an LLM client; no deterministic fallback. |
| `cli.py` | `generate` / `validate` subcommands. Unregistered (no HTTP/catalog). |
| `execution.py` | LangGraph: prepare_input â†’ plan_verifications â†’ investigate â†’ generate â†’ execute_tests â†’ evaluate â†’ (repair â†º) â†’ finalize. |
| `llm_client.py` | `ProviderProbeLLMClient` (dev-agents.yaml entry, default `dummy`; paced RPM/TPM) + `ScriptedProbeLLMClient` for offline tests. |
| `investigation.py` | Bounded read-only LLMâ†”tool loop (list_files/read_file/search_text/search_imports), confined to the disposable copy. |
| `schemas.py` | Typed contracts. Generation states (`generated`/`invalid`) are separate from execution outcomes. |
| `packaging.py` | Deterministic ZIP build: `.tallercito/` with runner, scripts, `manifest.json` (schema 1.1), report. |
| `tests_local/` | Offline acceptance tests (12) on a synthetic repo fixture. |

Shared machinery (extracted from `finding_test_generation`):
`src/server/runtimes/verification/` (`tools/`, `templates/`, `zip_pack.py`,
`zip_validate.py`, `checkout.py`). Node execution uses
`runtimes/verification/templates/node_runtime.py` (lane-neutral: install with
`--ignore-scripts` in disposable copies only, vitest with TS/TSX/jsdom harness
pinning Vitest 4 / React 19 / jsdom; `node:test` as optional fallback).

## Input contract

The findings document is the **raw result JSON of a testability investigation**
(`artifacts/test-isolation-*.json` / `test-controllability-*.json`), i.e.
`{repository_id, commit, snapshot_hash, objective, findings: [...]}`. It is
*not* the audit-export format. `architecture_context.json` may be passed as
complementary context (a bounded digest is injected into planning prompts).
Empty findings â‡’ valid termination `no_findings` with an empty suite â€” the
project is not declared defect-free, nothing was claimed.

## Usage

```powershell
# Generate (reads the investigation export; never modifies the audited checkout)
uv run python -m server.agents.testability_probe.cli generate `
  --findings artifacts\test-controllability-civitaspermit-004.json `
  --repo examples\testcontrollability\civitaspermit-01\repository `
  --architecture-context examples\testcontrollability\civitaspermit-01\architecture_context.json `
  --output artifacts\testability-probe\civitaspermit-01\run-3 `
  --allow-local-unsafe-execution --json

# Re-execute a previously exported suite without any LLM (CI / later commits)
uv run python -m server.agents.testability_probe.cli validate `
  --zip <suite.zip> --repo <checkout> [--target-commit <sha>]
```

`--allow-local-unsafe-execution` is required for in-loop RED validation; it is a
development escape hatch, **not** a security sandbox (disposable copy, `uv`/
pytest subprocess with a minimal environment, no network required by the tests
itself). Without it, suites are exported unvalidated.

Fields kept by the manifest per verification: `finding_id`, `condition`,
`language`, `framework`, `evidence_refs`, `source_commit`, plus the runner's
`verification_id/test_path/strategy/covered_property/target_components` and
separate `generation_status` / outcome axis.

## Evaluation status (2026-11-15, `dummy` = gemini-3.5-flash-lite)

Regression (defects and negative controls), 4/4 suites validate end-to-end:

| Project | Findings | Shipped | RED present | Suite |
|---|---|---|---|---|
| civitaspermit-01 | 8 | 8 | 7 | `artifacts/testability-probe/civitaspermit-01/node-20261115T182456/` |
| galleryforge-01 (negative) | 0 | 0 | – | `artifacts/testability-probe/galleryforge-01/node-20261115T182456/` |
| harborcold-01 | 10 | 9 | 7 | `artifacts/testability-probe/harborcold-01/node-20261115T182456/` |
| vetoria-01 (negative) | 0 | 0 | – | `artifacts/testability-probe/vetoria-01/node-20261115T182456/` |

Polleria (real polyglot repo, 18 testability findings). Node lane: TS tests with
the TypeScript compiler API ran against real project sources installed in the
disposable copy; 10 violation_present (static AST oracles), 5 technical, 2 LLM
inconclusive; TSX suite uses `node:test` runtime only when explicitly targeted.

## Evaluation status (2026-11-15, `dummy` = gemini-3.5-flash-lite, after presence-oracle fix)

| Project | Findings | Planned | Shipped | RED detected | invalid_test (dropped) | Artifact |
|---|---|---|---|---|---|---|
| civitaspermit-01 | 8 | 8 | 4 | 4 | 4 | `artifacts/testability-probe/civitaspermit-01/node-20261115T200955/` |
| harborcold-01 | 10 | 10 | 7 | 7 | 3 | `artifacts/testability-probe/harborcold-01/node-20261115T200955/` |
| galleryforge-01 (negative) | 0 | 0 | 0 | – | 0 | `artifacts/testability-probe/galleryforge-01/node-20261115T200955/` |
| vetoria-01 (negative) | 0 | 0 | 0 | – | 0 | `artifacts/testability-probe/vetoria-01/node-20261115T200955/` |
| polleria | 18 | 17 | 15 | 10 | 2 | `artifacts/testability-probe/polleria/node-20261115T195715/` |

Notes from this run:
- Presence/weak oracles no longer ship. A test that passes at the RED baseline is
  deterministically classified `invalid_test` (never `not_observed_within_scope`)
  and is excluded from the packaged suite.
- LLM-free re-execution of the packaged Polleria suite against the violating
  checkout: `VIOLATION_PRESENT` ×10, `NOT_VERIFIABLE` ×3, `EXECUTION_ERROR` ×2,
  and no `VERIFIED_FIXED`-style verdict anywhere (the exported runner now maps a
  bare pass at one checkout to `INCONCLUSIVE`).
- Repositories audited remain pristine (`repository-integrity.json`: unchanged on
  all five runs).


TSX structural verifiers abort with `OBSOLETE_VERIFIER` if the subject
disappears. Absence-vs-presence oracles in `generate_test.md`/`generate_node_test.md`
enforce FAIL-at-baseline semantics.

## Evaluation status (2026-11-14, `dummy` = gemini-3.1-flash-lite, historical)

| Project | Findings | Planned | RED reproduced | Shipped | Suite |
|---|---|---|---|---|---|
| civitaspermit-01 | 8 | 10 | 7 | 8 (7 RED + 1 inconclusive) | `artifacts/testability-probe/civitaspermit-01/run-4/` |
| solsticegrid-01 | 8 | 10 | 5 | 6 (5 RED + 1 not_observed) | `artifacts/testability-probe/solsticegrid-01/run-3/` |
| harborcold-01 | 10 | 12 | 7 | 7 (7 RED) | `artifacts/testability-probe/harborcold-01/run-1/` |
| lumenlib-01 | 9 | 12 | 11 | 11 (11 RED) | `artifacts/testability-probe/lumenlib-01/run-1/` |
| stagecraft-01 | 9 | 11 | 8 | 9 (8 RED + 1 not_observed) | `artifacts/testability-probe/stagecraft-01/run-1/` |
| galleryforge-01 | 0 | 0 | â€“ | empty suite, `no_findings` | `artifacts/testability-probe/galleryforge-01/run-2/` |
| vetoria-01 | 0 | 0 | â€“ | empty suite, `no_findings` | `artifacts/testability-probe/vetoria-01/run-1/` |

**Totals:** 55 planned verifications, **38 RED**, 41 shipped, ~255 LLM calls, ~347k tokens. All seven repositories audited remain pristine.

Notes from real runs:
- Generation quality degrades under free-tier 503/429; affected verifications are marked `not_generated` and excluded from the packaged suite (never fabricated).
- 3 of 10 civitaspermit tests were rejected as vacuous (`trivial_reason`); harborcold/lumenlib/stagecraft RED oracles held up strongly (7/7, 11/11, 8/9 executable).
- Tests that PASS at the RED baseline are classified deterministically `invalid_test` (presence/weak oracle) and dropped from the ZIP before packaging — never `not_observed_within_scope` or a LLM-selected verdict. The LLM evaluation only judges AssertionError-failing candidates (violation_present / invalid_test / inconclusive).
- `validate` re-executed the Polleria suite LLM-free and re-detected 10/10 AssertionError oracles at the violating checkout; the in-loop-to-runner mapping never claims a fix: a bare pass is `INCONCLUSIVE`, never `VERIFIED_FIXED` (verified status requires the bundled `green_control` execute option, which compares a failing baseline against a passing control and marks `validated_red_green`). Read `generation_status` in `manifest.json` for shipping evidence (`validated_red` / `partially_validated`); no single-checkout verdict is proof of a fix.
- Every RED verification FAILS with `AssertionError` on the denounced condition; failures caused by missing imports, fixtures, configuration or timeouts are classified `technical_failure` and repaired within budget, never reported as violations.

## Known limitations

- GREEN validation (corrected counter-example) is omitted: building one means
  implementing fixes in the audited repo, which is out of scope. RED-only is
  validated; GREEN is reported as unavailable.
- "No injection seam" oracles must be static (signature/AST) to surface as
  AssertionError; dynamic injection probes fail as `technical_failure`, not RED.
- `glob`/regex search and AST helpers are complements to LLM reasoning, never
  its replacement; there are no per-project rules.
- `validation_status=validated` proves only "the denunciated condition was
  observed at this commit in the declared scope", never that any finding is fixed.

## Integration (2026-11-15)

Production generation now uses explicit shared **Verification Suite** model
settings and credentials sent by the backend (`config.model` / `config.api_key`).
It does not read `dev-agents.yaml` or `.env`. The standalone CLI retains its
development resolver (`--agent-config dummy`, `LLM_API_KEY`). Settings discovery
exposes only the internal `verification_suite` model owner; neither generator is
registered for `/api/agents/run`. Re-execution remains model-free.

The probe and FindingTestGenerationAgent are now invoked by the
`/api/audits/{run_id}/verification-suite` endpoint (Split by
`subcharacteristic`, launched in parallel via `asyncio.gather`) and packaged
into a single `.tallercito/` ZIP:

- Unified runner: `--list-groups` and `--only <group>`; exit codes unchanged.
  `group` is the finding's `subcharacteristic` (`testability`, `modularity`,
  â€¦). The merged manifest is `schema_version 1.1` and tags every verification
  with `generator` (`finding_test_generation` | `testability_probe`) and `group`.
- The backend proxy accepts optional `group` for `execute` (pattern
  `^[A-Za-z0-9_-]{1,32}$`) and threads it into the agent-server's runner;
  `action=create` rejects `group` with HTTP 400.
- The frontend verification tab shows per-group tabs (options are derived from
  the built suite, not from a fixed taxonomy) and badges of `group` per row.
- Both agent packages are authorized in `agent-server/AGENTS.md` (rule 6).
- Findings whose `subcharacteristic` has no assigned generator (`other`) are
  never silently dropped; they are reported in the suite's limitations.

## Pending before hardening

### Completed evaluation with renewed provider quota (2026-11-16 UTC)

The real model (`gemini-3.5-flash-lite`) generated/repaired the code; no generated test
was hand-fixed or removed to improve the result. Failed versions remain in their original
artifact directories and `candidates.json` histories. Completion was iterative, not a claim
that the first fresh generation was perfect (that run produced 13 RED + 4 invalid tests).

| Repository | Final frozen execution | Evidence |
|---|---|---|
| Polleria | 18 findings covered, 18/18 `VIOLATION_PRESENT`, no errors | `artifacts/testability-probe/polleria/verified-18-20261116/` |
| civitaspermit-01 | 8/8 `VIOLATION_PRESENT` after repair | `artifacts/testability-probe/civitaspermit-01/node-20261116T031305/repair-replay-20261116T035144/` |
| harborcold-01 | 10 RED in the real-model generation run | `artifacts/testability-probe/harborcold-01/node-20261116T031305/` |
| galleryforge-01 / vetoria-01 | `no_findings`, zero generated tests | respective `node-20261116T031305/` directories |

Polleria's final ZIP is assembled from validated batches without changing test code;
`provenance.json` records original artifacts, metadata-only ID remapping and source hashes.
`execution.json` records model-free execution of the complete final ZIP. Repository status
remained unchanged. This does not certify any production fix: the real repositories were
checked in their audited states. An automated synthetic RED/GREEN acceptance test separately
checks that a repaired oracle passes the corrected control and the exported suite uses no LLM.

The general fixes are: system-role oracle instructions separate from candidate/source data;
removal of unvalidated plan snippets from code-authoring/evaluation authority; real relevant
Python function context beyond head truncation; a larger bounded per-component excerpt for
long TS/TSX components; compiler-derived assignment-target facts; and re-authoring the same
test from evidence when local oracle edits fail (technical errors still use local repair).
No repository names or fixture-specific repair rules were added to the generator.

Current repair policy: technical failures, timeouts, trivial tests, passing RED candidates,
and LLM-rejected/ambiguous oracles enter the same bounded repair loop. Repair preserves
the intended property, not an inverted assertion; it must not manufacture RED when source
contradicts a finding. Test revisions and failures are retained in `candidates.json`.
Generated invalid tests remain in the ZIP after budget exhaustion with `generation_status=invalid`;
the runner reports them as `EXECUTION_ERROR`, never approval. Missing code is reported separately.
`VERIFIED_FIXED` requires a passing execution plus previously recorded RED validation;
the earlier sections' discard/INCONCLUSIVE policy describes historical runs, not current delivery.

Real-model evaluation of this repair policy (`gemini-3.5-flash-lite`):
- `polleria/node-20261115T234736`: 17 planned, 15 generation failures under provider 429,
  2 generated non-discriminating tests retained. Focused real-model repair replay in
  `repair-replay-20261115T235845` also received 429 on all repair requests; both frozen
  verifiers re-execute as `EXECUTION_ERROR`. This is blocked, not a successful quality evaluation.
- `civitaspermit-01/node-20261115T234741`: 5 RED, 2 invalid retained, 1 generation failure;
  3 repair requests were attempted. Provider 429 prevented completion; harborcold access
  check also failed with 429. Galleryforge/vetoria remained `no_findings`.
- Repository status remained unchanged. These runs do not establish that all oracles
  are repaired or prove absence of overfitting; repeat after provider quota is available.

- The absence-vs-presence oracle guidance is now explicit in both generation
  prompts; any run already packaged from the earlier prompts retained
  presence-passing verifiers and should not be reused as a canonical artifact.
- Polleria (2026-11-15): after wiring the Node lane, one direct real run
  planned 10 verifications, shipped all 10 (7 violation_present, 1 technical
  failure on the Python lanes, 2 inconclusive) against 18 testability findings.
- GREEN validation (corrected counter-example) is omitted: building one means
  implementing fixes in the audited repo, which is out of scope. RED-only is
  validated; GREEN is reported as unavailable.
- "No injection seam" oracles must be static (signature/AST) to surface as
  AssertionError; dynamic injection probes fail as `technical_failure`, not RED.


