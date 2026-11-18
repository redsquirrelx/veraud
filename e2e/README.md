# Veraud E2E (black-box, Playwright)

Black-box end-to-end tests for Veraud: a real browser (Chromium), the real backend on `127.0.0.1:7601`, the real agent-server on `:7602`, and the real frontend on `:7600`. Every run is **fully isolated** from your developer environment:

- `e2e/.appdata/` is a fresh scratch directory rebuilt on every run:
  - `database.db` — a synthetic SQLite template seeded from migrations + `helpers/seed.mjs`
  - `execution-events.sqlite3`, provider quotas and `.secrets/` likewise disposable
  - `workspace/` — a synthetic Git repository (owner `e2e-owner`, name `e2e-sandbox`, branches `main` + `feature/sample`), created by `helpers/git-repo.mjs`

  Nothing inside `appdata/` or the developer database is read or written by these tests.

## Requirements

- `pnpm` on the PATH (used to launch backend, frontend and the prisma CLI)
- Node >= 22, `uv` on the PATH (agent-server)
- `git`
- Internet access **only** to `cdn.playwright.dev` the first time you install browsers (`pnpm exec playwright install chromium`)
- Windows only: the credential cipher uses DPAPI; key is created under `e2e/.appdata/workspace/.secrets` on first boot.

## Commands

```bash
cd e2e
pnpm install
pnpm exec playwright install chromium   # once

pnpm test          # headless, default
pnpm test:headed   # visible browser window
pnpm test:ui       # Playwright UI mode (time travel, watch mode)
pnpm test:debug    # step-by-step inspector
```

`pnpm test` rebuilds the fixture environment, boots all three services in the background, runs in order (`workers: 1`: tests share one running stack by design) and tears them down. Traces and screenshots are retained only on failure.

## Seeds (seed-state.json)

`e2e/.appdata/seed-state.json` pins the identifiers (project, versions, evaluations and executions) the suite asserts against. The seeded commit hashes are filled in at setup time from `git rev-parse` in the synthetic repository, with fixed author/committer dates.

Seed contents:

| Kind | State | What it proves |
| --- | --- | --- |
| Maintainability audit #1 | running | Explorer/drawer live states, receipts (manager → coordinator → modularity/complexity) |
| Joint audit — maintainability #2 + security #3 | completed | Shared evaluation, pipelines in the same row, receipts incl. nested SAST |
| Maintainability audit #4 | failed | Error surface, sanitized error text, no cancel action |
| Dedicated audit #7 | running | Cancel flow (mutation isolates itself to its own row) |
| Architecture context #5 | completed | Standalone agent without nested receipts |
| Verification suite #6 | running | Standalone agent with nested receipts (finding_test_generation completed, testability_probe running → tree renders) |

Plus: one evaluation row per audit, agent catalog `agent_settings`, the project with `READY` status, `main` selected, `feature/sample` present.

## Live tests (opt-in)

`tests/live/*.spec.ts` are skipped unless `VERAUD_E2E_LIVE=1` is set — they hit the network and/or real model smoke paths:

```bash
VERAUD_E2E_LIVE=1 pnpm test                         # register octocat/Hello-World against github.com
VERAUD_E2E_LIVE_REPO=https://github.com/owner/repo VERAUD_E2E_LIVE=1 pnpm test
VERAUD_E2E_LIVE=1 AGENT_SERVER_SMOKE_MODELS=1 pnpm test   # architecture pipeline with the agent-server's offline smoke models
```

Never enable both in CI — they are manual pre-release checks only.

## Known limitations

- Maintainability audits cannot run offline for real: the E2E seed exercises read paths, receipts rendering, cancellation and error surfaces; actual inference is covered elsewhere.
- The 1 active-execution badge count and the "Cancelling…" transient state updates rely on the WS handshake at the backend; tests instead assert persisted truth (row contents after refresh, status badges, navigation, API-visible state).
- The sandbox checkout is committed with fixed dates for stable history; hashes are not hardcoded anywhere.
