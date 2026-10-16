# Architecture Component Diagrams

The architect chooses the component view in a dedicated compact composition step
after repository investigation, before semantic review. Its main investigation prompt
excludes the diagram contract. The composition prompt contains report summaries and
exact unit/connection references, not tools, source bodies, inventories, or the complete
investigation history. It uses one logical model call per report; provider retries still
follow the shared gateway policy. No new repository reads are performed for composition.

The model chooses which components matter, how to group them, what relations to show,
and what to omit. The host validates that selection and deterministically renders
Mermaid; it does not fill in omitted nodes or replace a failed selection with a mechanical
view. `relationship` is available when the report does not justify a more specific type.
Scope, grouping, and relation types are then reviewed with the architectural claims.

Composition is bounded to a 16,000-character prompt, 12,000-character parsed response,
and a requested 1,200-token output limit (or the configured limit if smaller). The CLI's
configured Gemini adapter enforces that output limit; other adapters can implement
`generate_with_output_limit` to honor it, otherwise their existing output limit applies.
Summaries are capped at 300 statement characters and marked when truncated. Failures
retain the architectural report and expose composition issues without a format-repair
loop. Token admission follows the architect's advisory/strict configuration, while the
shared elapsed deadline remains enforced.

## Structured contract

```json
{
  "title": "Inspected component view",
  "scope": "Selected application",
  "groups": [
    {"id": "backend", "title": "Backend", "scope": "src/server"}
  ],
  "nodes": [
    {"id": "use_case", "unit_ref": "/organization/0", "group_id": "backend"},
    {"id": "port", "unit_ref": "/organization/1", "group_id": "backend"},
    {"id": "adapter", "unit_ref": "/organization/2", "group_id": "backend"}
  ],
  "edges": [
    {"source": "use_case", "target": "port", "kind": "depends_on", "claim_ref": "/connections/0/description"},
    {"source": "adapter", "target": "port", "kind": "implements", "claim_ref": "/connections/1/description"}
  ],
  "limitations": ["Runtime composition remains unverified."]
}
```

This example requires matching organization units and connection claims in the same
report. Node labels, responsibilities, certainty, and evidence are inherited from
those units rather than authored a second time. Edges reference a connection's claim
and inherit its certainty/evidence. `claim_ref` can also point to
`/closest_architecture/observed_dependencies/0/description` or
`/closest_architecture/observed_paths/0/0/description`.

Kinds are explicit:
- `relationship`: reproduces the referenced directed claim without introducing a subtype;
- `calls`: invocation or communication, requiring observed implementation behavior;
- `depends_on`: static dependency;
- `implements`: implementation/inheritance of a contract, directed adapter -> port.

For example, `UseCase -> Port <- Adapter` represents inversion relationships, not
an asserted linear runtime request path. Frontend/backend grouping is allowed when
justified by the implementation. The diagram must describe observed organization
instead of adding conventional layers to resemble the selected architectural pattern.

The contract allows up to 12 nodes, 16 edges, and 4 nonempty groups. The current
organization contract limits the distinct units to 8. Smaller or ungrouped diagrams
are valid. IDs must be simple lowercase identifiers; the renderer independently uses
safe generated Mermaid IDs. Labels are escaped and multiline text is normalized.

## Validation and partial recovery

Structural validation rejects missing units/groups, duplicate units, missing edge
endpoints, unavailable claim pointers, and reversed connection directions. Existing
architectural source-reference validation applies to the linked claims. A malformed
diagram is omitted during partial salvage while valid report sections are retained;
the report records the omission in its uncertainties.

The semantic validator reuses the original responsibility/connection targets. Only
new interpretations add review targets:
- `/diagram/scope` for the view title and declared scope;
- `/diagram/groups/{index}` for grouping responsibilities;
- `/diagram/edges/{index}` for typed directed relationships.

These derived targets for authored views inherit source hints, evidence IDs, scope, and uncertainty from
their linked claims; they still require independent validator inspection. In particular,
a supported import does not automatically establish a `calls` relation. Diagram targets
are appended after the existing high-priority architectural targets. When the review
claim cap excludes them, they remain pending; increase `--max-review-claims` if needed.

Diagram annotation verdicts combine relevant claim, scope, grouping, and relation-type
findings. A node/edge is marked semantically supported only when all its relevant
targets were reviewed and supported. Contradiction/overstatement takes precedence;
missing findings yield `not_reviewed`. This does not upgrade an architectural hypothesis.
Solid edges indicate architect-supported claims; dashed edges indicate hypothetical
or unresolved claims. Semantic status is separately labeled, including pending review.

## CLI

```powershell
uv run python -m server.run_project_architecture <checkout>
uv run python -m server.run_project_architecture <checkout> --validate-semantics
uv run python -m server.run_project_architecture <checkout> --validate-semantics --json
```

Diagram composition runs by default and prints a Mermaid block after the normal
human-readable summary. Use `--no-diagram` to skip it. Use `--diagram --json`
only when you need to force the view in JSON mode (JSON output contains
`architecture_diagram` when a valid view was produced; the
flag does not append Markdown to JSON). If no view is present, the field is null and
the run reports its unavailability. Older reports without a diagram remain valid.

The top-level architectural report remains original in the CLI JSON envelope, while
`architecture_diagram` corresponds to the **displayed** report: revised if a revised
report exists, otherwise original. It includes `report_origin`, `snapshot_hash`, and
`report_hash`, so consumers can verify which report it illustrates. The independent
semantic review runner also exports the original report's diagram with review annotations.

## Recovery after a provider failure

The CLI atomically saves the architectural report **before** asking
for the component view. The summary and JSON expose `architecture_checkpoint`; the
default is `.architecture-checkpoints/<repository>-<path-hash>.json` under the current
directory. Use `--checkpoint <file>` for an explicit location. A revised report is
saved before its new composition as well. Checkpoints contain report citations and
telemetry, not model credentials. They are ignored by Git.

Retry composition without orientation or investigation:

```powershell
uv run python -m server.run_project_architecture <checkout> --resume-report <checkpoint.json>
```

`--resume-report` implies `--diagram`. It still collects a snapshot to ensure that the
saved report's evidence belongs to the current checkout; a snapshot mismatch fails
before provider calls. It does not repeat investigation or source retrieval. Semantic
review is optional with `--validate-semantics`; without that flag the recovered view
is pending semantic review. If requesting review, it runs after the recovered selection.

Choose another model for composition only:

```powershell
uv run python -m server.run_project_architecture <checkout> --resume-report <checkpoint.json> --diagram-model <model-name> --validate-semantics
```

`--diagram-provider` and `--diagram-api-key` optionally override that stage's provider
and credentials. Defaults inherit the main model configuration. Diagram retries use
`--diagram-retry-backoff` (default 10 seconds, then 20 seconds for the second retry),
honor provider retry hints, and remain bounded by the shared execution deadline and
`--max-retries`. The CLI uses independent presentation failure state so an exhausted
diagram call does not automatically skip semantic review. Shared-client stages retain
request pacing. HTTP 503 remains a provider failure; recovery does not fabricate a view.

## Backend and library

`ProjectArchitecturePipeline.run(..., include_diagram=True)` composes by default
for backend callers. Set it to false to omit the additional call.
The CLI composes by default; pass `--no-diagram` to skip. The pipeline exports
`diagram_composition` with its source report hash, accepted selection, issues, usage,
and role-local telemetry. A revised report is composed again before revalidation;
that result is preserved as `semantic_validation.diagram_revision`. It is never
composed after semantic acceptance using an unevaluated view.

`ProjectArchitecturePipelineResult.diagram` is a typed `RenderedArchitectureDiagram`:
- `structure`: the selected report's structured diagram;
- `mermaid`: deterministic Mermaid source;
- `report_origin`, `snapshot_hash`, `report_hash`: exact report identity;
- `nodes` and `edges`: annotations with claim references, relevant review target IDs,
  evidence IDs, architect certainty, and semantic status;
- `limitations`: the view's declared omissions/uncertainties.

## Frontend

The backend merges the pipeline-level rendered diagram into the finished
`architecture` execution row as `architecture_diagram`
(`mermaid`, `report_origin`, `report_hash`), so the project detail page renders
it from the same result it already parses — no extra endpoint. The Architecture
section shows the Mermaid chart (lazy-loaded `mermaid`, SVG with source fallback
on parse failure) with the displayed report's origin; runs without a diagram
(predating diagrams, `--no-diagram`, or failed composition) keep the previous
structured shape footnote instead.

The pipeline selects the revised diagram when available and only uses matching
semantic review findings. A revision that has not been revalidated is rendered with
`not_reviewed` annotations, not the prior report's verdicts. Original/revised structured
views remain preserved in the report history. A revised report without a diagram does
not silently inherit the older view.

For direct agent callers:

```python
from server.agents.project_analysis.project_architecture import render_diagram, render_mermaid

artifact = render_diagram(architecture_result)  # no semantic review implied
mermaid_source = render_mermaid(architecture_result.architecture)
```

For direct agent use, call `await architect.compose_diagram(fresh_tools, report_result)`
after `architect.run`. This returns a separate `DiagramCompositionResult`; attach its
accepted diagram to a copied report before semantic review. The original report is
not mutated by composition. The full pipeline performs this attachment and ordering.

If you pass `findings`, they must belong to that exact report; the full pipeline performs
that report-matching check. The backend can render Mermaid or consume `structure` for
another renderer. No frontend rendering dependency or HTTP contract is changed here.

Tests cover direction, invalid references, source inheritance, independent interpretation
targets, safe labels, hypotheses, partial salvage, nested classification links, CLI JSON
separation, and selecting a revised diagram with its own review. Offline tests establish
these structural behaviors, not model accuracy in selecting a representative view.
