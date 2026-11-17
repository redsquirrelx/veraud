# Real-model validation — ecommerce and Pollería

Date: 2026-11-16. Graph nodes, edges, routers and state contract are unchanged.
Only this investigator, its local tests/docs and its dedicated runner were changed.

## Reproduction and provenance

Artifacts are under `C:\Users\Duck\AppData\Local\Temp\opencode\`.

- Ecommerce source: `agent-server/examples/shoplab-ecommerce/repository`.
  It has no independent Git repository. An unchanged temporary copy was versioned
  as `boundary-ecommerce-repository`, commit
  `41bedaa425d9358488062513fc02a50fb2d79978`. No oracle files were copied into it.
- Pollería source: `appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria`,
  commit `b516646312b44b24c42b608fa9d379922b34ee08`. Audited read-only in place.
- Frozen contexts: `boundary-ecommerce-context-flash.json` (131 claims) and
  `boundary-polleria-context-flash.json` (141 claims). Both are native
  `ArchitectureContextResult` outputs, generated with `gemini-3.5-flash`.
  Both have `execution_status=partial`, `finalization_reason=extraction_failed`
  and zero validation errors. Provider daily quotas prevented full extraction;
  these are not exhaustive specifications. The ecommerce context contains the
  normative architectural rules. No later context was substituted during tuning.
- Investigator: `--agent-config dummy --model gemini-3.1-flash-lite`.
  The original `dummy` model (`gemini-3.5-flash-lite`) exhausted its daily quota;
  `gemini-2.5-flash` was unavailable for generation and `gemini-3.5-flash`
  exhausted its smaller daily allowance during context extraction.
  No provider configuration or credentials were changed.
- Evaluation config: `boundary-evaluation-config.json`, containing only
  `{"max_planned_investigations": 15}`. This is the existing supported maximum,
  not a required quota. Global budgets remained disabled as configured.

From `agent-server/`, the final commands were:

```powershell
$artifacts = 'C:\Users\Duck\AppData\Local\Temp\opencode'
uv run python -X utf8 src/test-agents/run_architecture_boundary_doc_driven.py "$artifacts\boundary-ecommerce-repository" --architecture-context "$artifacts\boundary-ecommerce-context-flash.json" --config "$artifacts\boundary-evaluation-config.json" --model gemini-3.1-flash-lite --output-file "$artifacts\boundary-ecommerce-findings-final.json"
uv run python -X utf8 src/test-agents/run_architecture_boundary_doc_driven.py ../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria --architecture-context "$artifacts\boundary-polleria-context-flash.json" --config "$artifacts\boundary-evaluation-config.json" --model gemini-3.1-flash-lite --output-file "$artifacts\boundary-polleria-findings-final.json"
```

Contexts are tied to the indexed root and commit. Moving the temporary fixture
requires regenerating its context; never rewrite provenance to force compatibility.

## Final output

| Measure | Ecommerce | Pollería |
|---|---:|---:|
| Selected investigations | 12 | 10 |
| Provisional candidates/findings | 10 | 7 |
| `finding_candidate` / `no_finding` / `inconclusive` tasks | 10 / 1 / 1 | 7 / 0 / 3 |
| Model calls/attempts accounted by runner | 16 | 15 |
| Tool executions | 30 | 21 |
| Accounted tokens | 122,237 | 132,860 |
| Estimated tokens included above | 0 | 19,685 |
| Documentary synthesis integrity issues | 0 | 0 |

Both outputs have `termination_reason=investigations_completed` and validate as
native `BoundaryResult`; every candidate's evidence IDs resolve in the ledger.
Completion does not mean every investigation was conclusive or findings confirmed.
The PowerShell capture reported a nonzero shell status; the figures above come
from the saved, schema-validated canonical results, not an assertion of exit code 0.

## Ecommerce: comparison with the evaluator-only oracle

The oracle is `shoplab-commerce-0.4.0-defects.json`, outside the audited repository.
It contains 36 defects: 9 `architectural_boundary`, 3 `encapsulation`, and other
functional/responsibility/privacy/abstraction categories. The strict denominator
here is the 12 boundary/encapsulation cases, not all 36. Comparison is semantic
and manually reviewed, never by requiring the LLM to reproduce oracle IDs.

- Matched **8/12**: `SL-A01`, `SL-A02`, `SL-A03`, `SL-A04`, `SL-A05`, `SL-A07`,
  `SL-P02`, `SL-I01`.
- Missed **4/12**: `SL-A06` (discount preview concrete adapter), `SL-A08`
  (catalog private state), `SL-C02` (customer-directory construction),
  `SL-UI01` (presentation bypass of composition root).
- All three historical expected IDs are covered semantically by the domain
  dependency and billing storage-access findings. These are two mechanisms,
  not three independent defects.
- Ten candidates represent eight distinct oracle cases. Billing storage access
  and procurement storage access each appear twice. Conservative synthesis does
  not merge different narratives merely because their paths overlap.
- No candidate flags the eight negative-control paths. This does not prove
  that all controls were fully inspected. No additional unmatched mechanism was
  counted in the final output.
- Detailed mapping: `boundary-ecommerce-evaluation.json` beside the output.

Earlier same-context/model executions retained 3 candidates / 20 calls / 151,592
tokens, then 3 / 25 / 186,894, then 8 / 17 / 127,816. The final run retained
10 / 16 / 122,237. One earlier run found `SL-A06`, which the final selection
missed. These stochastic samples demonstrate recovery improvements, not a
controlled benchmark or guaranteed recall. Development/context-generation cost
is additional to the final-run figures above; unsuccessful provider attempts and
earlier outputs/logs remain in the artifact directory.

## Pollería: transfer check after freezing the implementation

Seven distinct Route Handlers directly import `@/lib/prisma`:

| File (relative to Pollería) | Import line |
|---|---:|
| `app/api/customers/route.ts` | 2 |
| `app/api/accounting-periods/route.ts` | 2 |
| `app/api/purchases/without-voucher/route.ts` | 3 |
| `app/api/journal-entries/options/route.ts` | 1 |
| `app/api/cash-sessions/movements/route.ts` | 2 |
| `app/api/cash-sessions/[id]/close/route.ts` | 2 |
| `app/api/journal-entries/accounts/route.ts` | 1 |

Imports and query implementations were spot-checked against current source.
The rule is documented in
`specs/044-migracion-arquitectura-dominio-andamiaje-convencion/spec.md`, notably
lines 63 and 94. That specification also explicitly acknowledges staged migration
and existing handlers as technical debt (lines 167–169). These findings are
documented boundary deviations, not newly discovered functional/security bugs.

Investigations for `app/api/leaves/route.ts`, `app/api/journal-entries/route.ts`
and `app/api/orders/drinks/route.ts` remained inconclusive. They are not clean
bills. No Pollería oracle was supplied, so no recall or complete-coverage claim
is made. The agent was not retuned after observing these results.

## Offline checks

- 153 passed, 2 intentionally skipped (non-documentary runner variants).
- Ruff passes on this investigator and its dedicated runner.
- Existing fail-closed tests still reject assessments without chosen source,
  missing dependency endpoints, unknown/undelivered IDs and favorable-only claims.
- New synthetic tests cover ID locality, explicit graph-owner resolution and
  ambiguity, graph-vs-edge ranking, caller diversity, source-range defaults,
  path-alias scope enforcement and auditable reference-only normalization.
- No shared runtime, sibling agent, manager, provider config, oracle or audited
  source was modified. The original ShopLab example was not the final benchmark.
