# Architect Agent — Plan by Phases

The analyzer identifies *what* a project is. The architect describes *how it is
built*, reusing the analyzer's output as its starting point. Both always run
back to back: when an `analyzer` execution closes as `Completed`, the backend
opens the `architect` run on the same evaluation.

Decisions: the architect collects its own representations and reads code (it
does not work from the analyzer output alone); it describes plus reports risks
mapped to ISO/IEC 25010, with no scores. Structural fields
(`key_components`, `entrypoints`, `primary_language`) stay derived and
deterministic; the model only writes style, data flow, responsibilities, notes
and risks.

Test each phase on its own before moving to the next.

## Phase 1 — Compiling skeleton (no LLM)

- `agents/architect/{agent.py, schemas.py, __init__.py}` with `ArchitectInput`
  (`root_path`, `analysis`) and `ArchitectureDescription` (style,
  components, data_flow, third_party, cycles, quality_notes, risks,
  confidence).
- One-line registration in `app/agent_registry.py` plus a `dev-agents.yaml`
  entry (`temperature: 0.0`, generous timeout).
- `run()` stub returning a valid empty description.

**Test:** `GET /api/agents/architect/schema` and one run through the existing
`POST /api/agents/run` endpoint.

## Phase 2 — Collection and reading

- Integrate `CollectionService` and `evidence.read_excerpts` with the same
  budgets as the analyzer.
- `frame` node: given facts plus the analyzer's output, hypothesize the
  architectural style and what would confirm it.

**Test:** live run against a small repo; check `facts` and `pending` in logs.

## Phase 3 — Per-component characterization

- `survey → read → characterize`: read the analyzer's entrypoints plus
  `key_components`, then write one responsibility line per component citing
  what was read.

**Test:** the output holds one real path with a non-empty responsibility per
analyzer `key_component`.

## Phase 4 — Connections and risks

- `connect`: execution flow from entrypoints through components in prose,
  what cycles and hub concentration mean, what third-party dependencies say
  about persistence and external integrations.
- `map25010`: maintainability notes (modularity, analysability,
  modifiability, testability), each with `evidence: [paths]`.

**Test:** on a repo with a known cycle, `risks[]` cites it with paths.

## Phase 5 — Synthesis and partial determinism

- `synthesize` assembles the `ArchitectureDescription`. Structural fields are
  copied from the analyzer input; the model writes style, data flow,
  responsibilities, notes and risks only.
- Pure unit tests for the new schema readers and parsing (no model, no
  network).

**Test:** unit tests green plus two live runs showing identical components.

## Phase 6 — Backend chaining

- `AgentExecutionService.complete()`: when an `analyzer` run closes as
  `Completed`, open the `architect` run on the same evaluation with
  `{root_path, analysis}`. Never chain on `Failed`; never duplicate an open
  architect run.

**Test:** chaining tests (chains / does not chain / does not duplicate) plus
one live `POST /analyze` flow showing both runs in the Dock.

## Phase 7 — Surface (optional, last)

- Show style and responsibilities in the project header or Audits view.

**Test:** visual check in the browser.
