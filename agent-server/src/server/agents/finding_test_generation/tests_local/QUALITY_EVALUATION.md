# Provider evaluation — 2026-11-14

Scope: improve test authoring, not the evaluated repositories. Real provider calls used
the current `dummy` entry (`gemini-3.1-flash-lite` in the observed requests). Credentials
were loaded by the existing settings adapter, never copied into this report.

## General changes

- Pass original finding/documentary evidence to the author instead of just the derived plan.
- Treat catalog suggestions as fallible; prohibit undocumented vocabulary/class-count proxies.
- Supply bounded source context for referenced components and direct local imports.
- Use Path-normalized root instructions, including technical repair instructions.
- Fix the conditional that unconditionally skipped technical repair when its limit was absent.
- Preserve evaluation on Windows when subprocess output contains non-UTF-8 bytes.

No project-specific names or corrections were added to the authoring algorithm. Corrected
checkouts were available only to execution, not supplied in generation context. Evaluation
used existing corrected controls; no original project code was modified.

## Observed results (not a complete quality certification)

Outputs are outside this checkout under `../veraud-eval/`.

| Project / output | Accepted tests | Distinct findings covered | Evidence |
|---|---:|---:|---|
| metropulse-01/quality-v3 | 6 | 3/8 | RED in audited checkout, GREEN in existing corrected control |
| metropulse-01/quality-v4 | 5 | 3/8 | RED→GREEN; all accepted tests authored by LLM |
| shoplab-01/quality-v3 | 1 | 1/2 | RED→GREEN |
| shoplab-01/quality-v4 | 0 | 0/2 | No deliverable: candidates did not establish RED→GREEN |
| shoplab-01/quality-v5 | 1 | 1/2 | RED→GREEN; other test passed the violating baseline |
| urban-mesh/quality-v4 | 6 | 5/5 | RED only; no corrected control used in this run |

These are successive iterations, not a controlled same-model before/after benchmark.
Stochastic outputs varied. HTTP 503 failures occurred. A first metropulse run also exposed
the subprocess decoding bug and aborted; it is not counted as a successful evaluation.
Do not interpret aggregate `validated` from the existing pipeline as full finding coverage:
packaging can drop tests that fail control validation. The manifest describes shipped tests.

## Outstanding limitations

- Metropulse coverage remains incomplete; dynamic tests can still choose poor patch targets
  or fail under a legitimately refactored implementation.
- Shoplab retains a false-negative candidate; passing baseline tests need review, not a
  claim that the finding has been corrected.
- RED→GREEN against one corrected control is necessary evidence, not proof that an oracle
  accepts every legitimate correction or rejects every violating implementation.
- No unseen-project holdout or broad false-positive benchmark is claimed.
- Creating and running remain separate product actions. Evaluation CLI runs with local
  execution enabled do not make creation-time repository execution a requirement.

## Reproduction

From `agent-server`, for each available input/repository/control pair:

```text
uv run python -m server.agents.finding_test_generation.cli generate --findings <input.json> --repo <audited-checkout> --output <new-output-dir> --llm provider --allow-local-unsafe-execution --green-control <corrected-control>
```

Omit `--green-control` only for RED-only evaluation. Do not compare that result with
RED→GREEN coverage. Local regression checks:

```text
uv run pytest src/server/agents/finding_test_generation/tests_local -q
```
