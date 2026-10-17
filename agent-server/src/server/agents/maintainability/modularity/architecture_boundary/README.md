# ArchitectureBoundaryAgent

Independent ISO/IEC 25010:2023 modularity auditor. No pipeline registration,
coordinator, persistence, callbacks, or changes to the audited repository.

## Structured claim support

`BoundaryEvaluation.claim_checks` links each candidate and resolved hypothesis to
an explicit claim kind, exact file scope and observations backed by delivered source
IDs. Checks are required by host validation even for older responses that omit them.
Declarations, behavior, dependencies, isolation and absence of cycles have distinct
support requirements. Isolation needs implementation, usage and composition across
inspected endpoints; global conclusions cannot be justified by a port declaration.

A hypothesis check must also cover something the question itself names. Roles and scope
can both be satisfied by evidence from an unrelated subsystem: reading
`ai_service/http/routes.py` satisfies `behavior`/`implementation` and is internally
consistent, yet it cannot answer a question about `app/api`. When the hypothesis names
snapshot directories, a declared scope disjoint from all of them is reported as
`boundary_scope_unrelated_to_subject`, and the subject returns to investigation or the
conclusion is narrowed. Hypotheses naming no inspectable scope are not judged on this.
Candidates are excluded: their title, description and components derive from evidence
already observed, so scope drift there is much weaker evidence of substitution.

The host checks the syntax in the cited line ranges, not merely the file extension
or the reference's `source` label. Comment/docstring-only excerpts cannot establish
an implementation. Python and JS/TS role checks and TOML declaration checks are
supported; these are necessary syntactic checks, not proofs of runtime semantics.

`BoundaryReview` requires explicit scope support and the checked support IDs before
acceptance. Missing checks trigger bounded correction; substantive unverified claims
are returned to investigation when iterations, calls, tools and active time remain.
Finalization independently rechecks support, retains insufficient findings, and turns
unsupported resolved hypotheses into explained inconclusive results. `BoundaryResult`
retains claim checks, per-finding validation issues and the structured critical review
through coordinator/manager serialization and Blackboard publication.

Structural evaluation errors (missing/duplicate subject checks and directory scopes)
use the existing bounded evaluation corrections, with exact subject IDs and delivered
file references as correction data. This is distinct from acquiring missing evidence.
Parsed candidates are retained as insufficient partial work if structural repair
cannot complete within the available budget.

Review normalization retains known valid judgments, collapses identical duplicates,
and marks missing/conflicting/unsupported judgments insufficient. Unknown IDs do not
discard valid sibling judgments. Judging hypotheses instead of candidates is a metadata
defect the host can name exactly, so it triggers one bounded review correction even when
the candidate also carries support issues; otherwise the support issue would suppress
every retry and the real answer would be replaced by a placeholder. A candidate without
a judgment reports that the review answered other subjects, which is only called an
absent review when nothing was returned at all.

A resolved hypothesis or candidate that cites no delivered source evidence is not asked
for a claim check. That demand is unsatisfiable without fabrication: it only produced
empty support lists and consumed the correction budget. Instead
`evaluation_evidence_gaps` reports `boundary_no_delivered_source_evidence` with the
missing inspection, and routes the subject back to investigation. Finalization still
degrades any unresolved resolution without a check to `inconclusive`, so nothing is
accepted through this path. Per-candidate adjustments remain visible in
`critical_review.validation_issues`; expected IDs/support and the prior normalized
review are supplied for correction. Review metadata corrections share the configured
review-attempt allowance (including calls already spent on parsing/provider attempts),
and preserve the prior normalized review if subsequent correction is unavailable.

### Rejection states the alternative

`support_issues` proves that a check failed, not that a narrower one would pass. A single
read of a Python module usually carries `declaration`, `dependency` and `implementation`
at once, so rejecting it as `isolation` silently hides that the same cited lines already
support a valid finding. `satisfied_claim_kinds` re-derives the roles the cited syntax
actually shows and reports the kinds that would pass, as `satisfiable_claim_kinds` in the
recovery task and in the gap text. The role a support entry declares is the model's claim
about that range, so it is deliberately not reused for this test.

Nothing is rewritten. The model chooses, and a check whose support cannot cover its own
declared scope is offered no alternative. A narrower accepted finding is a real result;
a broadened claim that failed its evidence never is.

Every result retains the complete retrieved-evidence ledger in `AuditResult.evidence`,
verified against the commit exactly like cited evidence. A run whose provider fails
mid-evaluation still reports the bytes it inspected instead of an empty result.

A failed later evaluation repair does not replace the last structurally valid
evaluation. The attempted response remains separately available in
`failed_evaluation_attempt` with `evaluation_attempt_issues`. Reserved closing review
can still run after investigation exhausts its call allowance, retaining the original
termination reason and all hard provider/token/time limits. If there is no prior
valid evaluation, parsed incomplete candidates remain explicitly partial work.

An empty investigation answer with unchanged evidence and outstanding gaps is not
accepted as a decision that nothing remains. A provider can answer 200 while converting
its reply to no usable parts, so one corrective investigation call is spent with the
pending unread reads restated as data. Only a second degenerate turn with an unchanged
evidence fingerprint proceeds to closing review with `no_investigation_progress`, rather
than evaluating the same evidence again. The retry is an ordinary budgeted call: every
call, tool, token and active-time limit still applies, and no limit is relaxed.

Planning precedes every tool call, so no source excerpt can have been delivered yet.
Hypothesis `evidence_ids` that are not delivered evidence are discarded during
validation and the count is reported as an issue. They are never admissible downstream,
where they would deterministically fail as `unknown_evidence_ids`.

Recovery tasks suggest bounded unread function/method ranges for
missing roles; these are navigation only and never count as retrieved evidence.
Empty AI turns are omitted from provider prompts, without deleting graph history or
removing native tool calls and their responses.

A recovery task whose citation never resolved is otherwise empty: no path, no available
source, nothing actionable. Such tasks are grounded in the snapshot directories the
subject itself names in its question or evidence needs, exposed as
`navigation_scope_paths` with unread ranges under `next_source_reads`. Directory
existence is verified navigation, never evidence.

Isolation and absence-of-cycles evidence necessarily lies outside the declared scope,
and `scope_paths` can only widen once real support exists, so the model would otherwise
name the composition site in prose and never read it. When such a claim fails
`boundary_endpoints_not_inspected` or lacks a required role, `endpoint_source_reads`
proposes unread internal graph neighbours of the cited files. These hints never widen
`scope_paths` and never count as evidence: the model must actually read and cite a
neighbour before it can appear in the claim.

Reviewing an evaluation that produced no candidates cannot report unknown candidate
identifiers, because there is no candidate set to violate. Stray judgments are dropped
and recorded as `review_judgments_without_candidates`.

Native chat adapters receive `lean_schema()` for planning, evaluation and review,
matching the other specialized investigators. Generation hints and size bounds are
removed from the provider schema to reduce native-schema complexity; canonical
Pydantic parsing and host support checks still enforce the full contract locally.
Provider 400 diagnostics expose only fixed classifications and allowlisted request
fields from structured BadRequest details, never raw messages, descriptions or values.

### The lean schema is weaker than the contract, on purpose

`lean_schema()` strips `minItems`, so the provider is told that an empty `support`,
`scope_paths`, `components` or `evidence_ids` is schema-valid while canonical
validation rejects it as `too_short`. The generic correction advice for that code
refers the model to a schema which no longer contains the constraint it violated, so
in a real run it repeated the same payload until the correction budget was exhausted.

Two mechanisms keep that from wasting the budget again:

- `prepare_structured_input(node, value)` normalizes the parsed payload before
  validation. A claim check with empty `scope_paths` or `support` asserts nothing, so it
  is discarded and `validate_evaluation` reports the subject as `missing_claim_check`,
  which carries exact subject IDs and delivered source references. Discarded entries are
  logged with their count.
- `BoundaryEvaluation.validation_feedback["too_short"]` tells the model that an empty
  list is not a placeholder and that a subject it could not inspect belongs in
  `inconclusive` with a named next inspection, rather than an asserted claim.

Together these route a form-level defect into the semantic correction path, which is
the one that worked: after a `boundary_check_structure_invalid` error the model repaired
the omitted checks on its next attempt.

## Investigation discovery and coverage

The host supplies `boundary_coverage` from indexed cross-project/directory relationships,
including uninspected endpoints outside the initial inventory. `prioritized_source_reads`
ranks pending reads using hypothesis/objective terms, named paths, graph neighbours,
entrypoints, composition/configuration candidates and connectivity. Recovery also handles
module-level source and questions without literal directory names. Suggestions are
navigation only: no evidence is created until the repository tool delivers source.

`BoundaryResult.investigation_coverage` retains the complete indexed boundary map and
inspection counts, including on partial runs. Endpoint inspection is not semantic or
line-complete coverage. The prompt view bounds large inventories and reports omissions.
HTTP, shared-database and configuration coupling require explicit text searches and
source inspection; indexed edges do not establish their absence.

Strong claim checks reject unsupported indexed neighbours for isolation, indexed cycles,
unread indexed dependency-edge locations, and unresolved/dynamic dependencies in scope.
Cycle detection is scoped to the induced indexed file graph, not a proof about runtime
dependencies. Review remains responsible for semantic scope and architectural meaning.

Repeated turns without new delivered evidence trigger a strategy-change instruction and
then a bounded `no_investigation_progress` closing review, including nonempty responses.
Old uncited tool payloads can be compacted in provider copies of history; cited excerpts,
recent tool responses, tool-call pairing, graph history and the evidence ledger are
preserved. If pinned source/context still exceeds the hard cap, execution stops honestly.

Syntax validation covers Python and JS/TS (including `.mts`/`.cts`), plus declaration
support from parsed TOML/JSON/YAML excerpts. Other languages remain searchable/readable
but do not acquire syntax-validated roles. Narrative architecture rules still come from
caller context/criteria under the existing access policy.

## Token-efficient prompts and closing headroom

Native repository tool messages use the existing compact model projection, while the
full evidence/provenance ledger stays on the host and in the result. Boundary prompts
use citation IDs, file paths and line ranges without repeatedly transmitting hashes.
Planning/evaluation copies do not duplicate the hypothesis list. Evaluation/review
omit discovery inventories and navigation rankings; older metadata-only tool payloads
are compacted, with source citations and native tool-call pairing preserved.

Planning asks bounded questions about concrete paths instead of exhaustive UI or
whole-service claims. Scoped observations can coexist with unresolved broader scope;
no uninspected region becomes compliant merely because the budget runs out.

Investigation admission leaves token headroom for evaluation/review, and evaluation
leaves headroom for review. When this ends exploration, an already-current evaluation
goes directly to closing review; new evidence gets a bounded evaluation attempt first.
Hard local/shared token, call, time and provider limits remain authoritative. Reservations
are estimates, not guarantees against unexpectedly large reported provider usage.
Logs expose the node, accounted tokens, next request reserve, closing headroom and
effective local token limit. Native schema overhead uses the actual provider schema.

## Offline test execution

```powershell
uv run pytest src/test-agents/test_architecture_boundary.py -q
```

The tests execute the real graph, native `ToolNode`, snapshot analysis and repository
queries with scripted model responses. No network, provider credentials or paid calls.

## Standalone live execution (from `agent-server`)

```powershell
uv run python src/test-agents/run_architecture_boundary.py C:\repos\project --request request.json
```

Provider, model, temperature and model output limit come from
`agent-server/config/dev-agents.yaml`, entry `agents.dummy` by default (the current
shared development configuration). Use `--agent-config NAME` to select another
existing entry. Credentials come from `LLM_API_KEY` in the repository-root `.env`,
resolved independently of the working directory; an environment variable of the
same name takes precedence. No provider-specific API-key variable is required.
Unit tests remain offline and do not load credentials or call a provider.

### LangSmith tracing

The live runner wraps the audit with the existing `LangSmithTracingBackend` via
`wrap_stage`. No pipeline registration or tracing code is added to the agent.
Use the repository-root `.env` (the same one used for `LLM_API_KEY`):

```dotenv
LANGSMITH_API_KEY=your-langsmith-key
LANGSMITH_PROJECT=agent-server
# Optional privacy settings:
LANGSMITH_HIDE_INPUTS=true
LANGSMITH_HIDE_OUTPUTS=true
```

Run the same `uv run python ...` command; no extra flags are needed. The backend
is a pass-through without a LangSmith key. With a key, the `architecture-boundary`
root span contains the native LangGraph graph, node/tool executions and LangChain
model calls, including structured-output correction attempts. The shared tracing
configuration also honors `LANGSMITH_ENDPOINT` and `LANGSMITH_TAGS`.

Root metadata includes repository identity, commit, snapshot hash, provider and
model, not API keys or repository content. **Unless input/output hiding is enabled,
traces can upload prompts, retrieved source and audit results to LangSmith.**
Embedding callers can wrap `agent.run(...)` with the same tracing port themselves;
the standalone agent remains independent of LangSmith.

The repository root and its parent are trusted host inputs, never tool arguments.
Output is JSON on stdout, with no automatic output file. Existing log configuration
may also emit diagnostics. Use a model supporting native tool calls and JSON responses.
The runner uses LangChain's installed provider integrations (`openai`, `anthropic`,
`google_genai`, or `openrouter`) because ReAct requires native tool-call messages;
the legacy Gemini text-only adapter cannot provide that contract.

Example `request.json`:

```json
{
  "objective": "Audit dependency direction and component boundaries",
  "architectural_context": "The domain owns ports; infrastructure implements them.",
  "criteria": [{
    "id": "domain-independence",
    "description": "Domain modules must not import infrastructure implementations.",
    "origin": "explicit",
    "provenance": "Architecture guideline supplied by the caller, revision abc123"
  }]
}
```

Caller context/provenance is declared input, not independently verified repository
evidence. Without explicit rules the default heuristic permits design observations,
never invented rule violations. Existing repository tools exclude narrative docs;
supply relevant documentation as architectural context/criteria. Do not broaden the
access policy to work around this restriction. Source text is untrusted data.

## Embedding

The investigation graph, budgets, evidence contracts and structured-output helpers
are shared in `runtimes/investigation/` with `ResponsibilityAgent`. This package
retains boundary-specific defaults/prompts and backward-compatible public imports;
its cognitive flow and audit behavior are unchanged by the extraction.

```python
agent = ArchitectureBoundaryAgent(chat_model, BoundaryConfig(max_iterations=3))
result = await agent.run(fresh_repository_toolset, AuditRequest(...))
```

An existing provider wrapper exposing `.llm` can also be passed. The caller owns the
model/client and supplies a fresh `RepositoryToolset` for each run. Runs hold no state
on the agent instance; native tool wrappers and graph state are private per run.
`BoundaryConfig.tools` selects from existing read-only tools. `ToolLimits` on the
toolset controls page/excerpt/response limits; repository execution budgets provide
additional hard caps. Prompt text can be overridden per cognitive node.

The graph is plan -> investigate <-> tools -> evaluate -> (investigate | review)
-> deterministic finalize. Routing reads validated sufficiency and host counters,
never an extra LLM. Model calls, evaluation iterations, tool calls, context size,
elapsed time and tokens are bounded. The host reserves evaluation/review model-call
slots; token/context/provider failure may still prevent review, in which case no
candidate is accepted. Unknown/failed provider usage is conservatively reserved
(0.5 tokens per serialized character plus the output allowance), kept separate from
reported usage. No automatic provider retries are configured by the live runner.

Planning, evaluation and review use native `with_structured_output` with JSON Schema
and `include_raw=True`, retaining provider usage even when output validation fails.
Simple custom/test adapters without native structured output use bounded JSON parsing.
Invalid structured responses get one regeneration by default (`max_schema_retries=1`,
configurable from 0 to 2), charged to the same call/token/time/context budgets and
leaving downstream model-call slots available. Provider request errors are not retried
as if they were invalid model output.

Diagnostics distinguish `structured_output_setup`, `provider_request` and
`response_schema`. Validation messages expose only known field names, positions and
error codes, never raw responses, source excerpts, arbitrary extra keys or credentials.
Truncated output is identified when provider finish metadata reports a token limit.

Native provider output caps are set on a shallow model copy, without changing the
caller-owned model. In particular, Gemini uses `max_output_tokens`: sending the
OpenAI-style call-time `max_tokens` argument causes a local SDK `ValidationError`
before any HTTP request. Offline regression tests exercise the actual Gemini adapter
and JSON-schema/usage handling with a mocked transport, requiring no real API key.

`findings` retains accepted, rejected and insufficiently supported candidates;
consumers must filter `validation_status == "accepted"` before reporting confirmed
issues. References are resolved from the delivered provenance ledger, never generated
paths/lines. Snapshot/content hashes identify actual bytes. When a base commit is
available, cited file bytes are checked against Git blob identities using read-only
queries; mismatched/unverifiable citations lose their commit attribution and the
candidate cannot be accepted. Without a commit, results explicitly remain snapshot-only.
For commit-exact audits, supply a clean checkout at the desired commit. Inconclusive hypotheses and
missing information remain visible on budget exhaustion. No findings is not a
certificate of compliance.
