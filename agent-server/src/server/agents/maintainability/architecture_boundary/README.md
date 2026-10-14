# ArchitectureBoundaryAgent

Independent ISO/IEC 25010:2023 modularity auditor. No pipeline registration,
coordinator, persistence, callbacks, or changes to the audited repository.

## Offline tests (from `agent-server`)

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
are shared in `agents/modularity_runtime/` with `ResponsibilityAgent`. This package
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
