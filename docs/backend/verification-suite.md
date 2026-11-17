# Verification suite

Builds a portable, LLM-generated **verification suite** from the findings of an
audit, and re-runs it against other commits without calling any model.

## Model configuration

Settings → Audit → **Verification Suite** owns shared provider/model access for
both generators. Select a saved credential and configure temperature and maximum
output tokens per call through the existing agent-settings drawer. Each generator
retains its own execution budgets; these are not the audit's token budget.

Generation verifies `verification_suite` access before dispatch and sends the
resolved model and API key explicitly to the agent-server. Missing/invalid access
returns 422 without launching a generator. Neither `dummy` nor the server `.env`
is a production fallback. Credentials are not included in status/artifact output.
Re-executing or downloading an existing suite does not require model configuration.

Standalone runners are unchanged: `--agent-config dummy` reads
`agent-server/config/dev-agents.yaml`, and `LLM_API_KEY` comes from the root `.env`
or environment. CLI temperature overrides remain local to the runner.

**Who does what**

| Layer | Responsibility |
|---|---|
| `POST /api/projects/:id/audits/:auditId/verification-suite` | Fire-and-poll entry; splits findings by `subcharacteristic` into two generator buckets and runs them in parallel. |
| FindingTestGenerationAgent | Verifies maintainability criteria (`architectural-boundaries`, `single-responsibility`). |
| TestabilityProbeAgent | Verifies the testability subcharacteristic (`test-isolation`, `test-controllability`). |
| `.tallercito/` runner | Portable runner; executes all or a subset of verifications offline. Python findings use pytest/uv; TypeScript/JavaScript findings use a pinned Vitest harness and optional project lock installation. |

Findings with a subcharacteristic nobody owns are not silently assigned to an
agent: they are listed in the suite's limitations as *unsupported*.

## POST — build (action `create`, default)

- Body (optional): `{ "action": "create" }`.
- Returns `202` and the run's status payload (`status: "building"`); poll the GET
  route until `ready` / `failed` / `recovering`. Does not run the suite.
- Produces one unified `.tallercito/` ZIP:
  - `manifest.json` (`schema_version` `1.1`, `runner` `uv`): union of all
    verifications from both generators, each with `group` (the finding's
    subcharacteristic), `generator` (`finding_test_generation` |
    `testability_probe`) and `generation_status`.
  - `tests/` shared between the generators; `docs/verification-report.md` covers
    both; `run.sh` / `run.bat` forward arguments to the runner.

## Execute (action `execute`)

Re-runs the built ZIP, optionally on another commit, without any LLM.

**Node verification lane.** When the suite contains TypeScript/JavaScript
verifiers the disposable copy runs `npm ci --ignore-scripts` (or `pnpm
install --frozen-lockfile --ignore-scripts` / `yarn install --frozen-lockfile
--ignore-scripts`) to restore project dependencies, plus a pinned harness
(`vitest` 4 / `typescript` / `react` / `react-dom` / `jsdom`) in
`.tallercito/node`. Use `--no-install` / `--no-install` flag on `cli validate`
to skip all dependency downloads; direct structural verifiers (static AST
inspection against the checkout’s source files) still execute.

Installation happens in the disposable baseline copy — never in the audited
checkout. `--ignore-scripts` prevents arbitrary lifecycle code and strips SQL
connection side effects; audited-checkout `.env` files are never copied or
exposed. If installation fails the affected verifiers fail as
`technical_failure` rather than fabricating outcomes.
```jsonc
POST /api/projects/9/audits/12/verification-suite
{ "action": "execute", "targetCommit": "<40-hex-sha>", "group": "testability" }
```

- `targetCommit` (optional): executes an immutable snapshot of that commit
  instead of the working tree. `group` (optional): limits the run to one
  verification group (regex `^[A-Za-z0-9_-]{1,32}$`). Both only valid for
  `execute`; requesting them for `create` returns `400`.
- The ZIP runner supports the same selection directly:
  `./run.sh --only testability` and `./run.sh --list-groups`.
- The response includes `selection` and `groups_present`.

## GET — read state

- `GET .../verification-suite?action=create|execute[&group=<name>]`: status
  read, never regenerates. When an attempt id is recorded, a stale or older
  attempt never surfaces; `groups` and `generators` summarise the built suite.
- `verification-suite-summary.json` (artifact) and the agent-server's
  `verification-suite/` output keep independent copies of each generator's ZIP.
- ZIP download: `GET .../verification-suite.zip`.

## Result semantics

Generation executes verifiers in disposable copies as well as on explicit re-execution:
the repair loop needs actual execution feedback. Repository source files are never repaired.
An exhausted repair budget preserves the generated test and diagnostics rather than removing it.
Public execution results are `VIOLATION_PRESENT`, `VERIFIED_FIXED`, or `EXECUTION_ERROR`.
A pass is approved only when the manifest records prior RED validation of that oracle;
an unvalidated pass, a skipped/uncollected test or an invalid oracle is an execution/validation
error, never evidence of a correction. Regenerate older unvalidated suites to obtain that evidence.

- `validation_status=validated|validated_red_green|partial|environment_blocked|inconclusive`: claims per
  verification; `violation_present` reproduces the denounced condition in the
  audited checkout; a bare, unvalidated pass is reported as `EXECUTION_ERROR` — it never means the
  finding is "resolved". `validated_red_green` requires both checkouts (violating baseline fails,
  green control passes) via the `green_control` execute option.
- `group` on each verification is the *subcharacteristic*: testability for
  isolation/controllability findings, modularity for boundaries/single-responsibility.
- `execution_error` / `technical_failure` are not violations. Trivial tests are
  rejected before execution. A suite that fails to collect cannot count as RED.
