# Code comprehension

`CodeComprehensionAgent` asks whether component responsibilities and behavior can be
understood without excessive ambiguity (maintainability / `analysability`). Names,
size, mixed responsibilities and structural edges are navigation, never standalone
defect criteria. A finding requires a concrete comprehension obstacle, observed
behavior, counterevidence analysis and independent review.

```python
from server.agents.maintainability.analysability.code_comprehension import (
    CodeComprehensionAgent, CodeComprehensionRequest,
)

result = await CodeComprehensionAgent(model).run(fresh_tools, CodeComprehensionRequest())
```

The agent inherits the shared `plan_investigation → investigate ↔ tools →
evaluate_evidence → investigate/review_findings → finalize` LangGraph. Finalization
does not invoke the model. Only accepted and host-validated findings are returned;
rejected/unsupported candidates remain diagnostics and critical review. Partial
investigation, uncertainty, source references and resource accounting are retained.

`targets` accepts exact accessible paths, file IDs or symbol IDs. The developer-only
`max_components` bounds the sample and `max_related_components_per_assessment` bounds
relied-on collaborators. Shared time/token/call/provider limits retain their ownership.
The model receives bounded source-navigation hints; cited source is pinned during
history compaction. Narrative documentation remains excluded by repository policy.

## Existing representations

The optional `representations` request composes the existing `OrientationResult`,
`ArchitectureResult` and `SemanticValidationResult` contracts, not parallel schemas.
Only same-snapshot, nonfailed results inform bounded planning. Semantic reviews
must refer to the supplied architecture when both are present. Previous claim
statuses, contradictions and limitations remain explicit. Earlier citations are
not imported as investigation evidence: supporting implementation must be delivered
by this invocation's `RepositoryToolset`. No other agent is launched automatically.

The investigator is discoverable as an internal participant and can publish through
the existing Blackboard lifecycle. Reports categorize it as analysability. It is
not attached to the quality-audit workflow or manager: no analysability coordinator
exists yet. No new direct HTTP execution endpoint is registered.

## Standalone demo (from agent-server)

```powershell
uv run python src/test-agents/run_code_comprehension.py src/test-agents/fixtures/code_comprehension --agent-config dummy
uv run python src/test-agents/run_code_comprehension.py C:\repos\sample --output raw
uv run --no-sync pytest src/test-agents/test_code_comprehension.py -q
```

The demo reuses existing model configuration/credentials, tracing, snapshot analysis,
read-only tools and client cleanup. Real calls may incur costs. `--request` accepts
the request and optional project representations; `--config` sets developer limits.
`--output readable` (default) explains conclusions, accepted findings, evidence locations,
component behavior, hypothesis resolution, rejected proposals, pending work and limits.
`--output raw` preserves the complete JSON result, including all technical fields.
Formatting is deterministic: neither mode reads source again or calls an LLM.
No source is executed or changed.
Git attribution can be unavailable for the fixture; snapshot hashes still identify
audited content. Tests use simulated models, without credentials or network calls.
