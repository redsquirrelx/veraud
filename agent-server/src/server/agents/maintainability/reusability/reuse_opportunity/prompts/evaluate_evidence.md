Return ReuseEvaluation: all hypotheses, candidates, group_assessments and precise
missing_information. Preserve stable group IDs and prior hypotheses; update their
status/rationale. Assess every planned group in hypothesis_scopes, or identify its evidence
blocker. Do not create gaps merely for unplanned discovery groups. Keep the original
question and binding; a comparison for one scope cannot resolve another hypothesis.
Only assess a new group after both complete member bodies have been delivered. For
other planned groups, report the exact missing source instead of inventing profiles.
Use the retrieval IDs in the delivered evidence ledger, not indexed discovery anchors.

Each group assessment names exactly the two selected component IDs and compares
their purpose, inputs_outputs, preconditions_postconditions, failure_behavior,
side_effects, dependencies and invariants. Cite delivered evidence_ids covering
each entire indexed implementation; a declaration, name, count or metadata is not
proof. Distinguish observed facts from inference in each explanation. Unknown
behavior is explicitly unknown, not assumed pure/equivalent. Unknown citation IDs
or invented locations cannot support conclusions.
Set behavior_basis=contract_only for protocol/interface/abstract/stub declarations.
Such declarations expose signatures, not implementation failure behavior, effects or
runtime invariants. Write 'Unknown from declaration' rather than 'None' or guessed errors.
Contract differences may justify not merging the inspected contracts, but do not prove
their implementations cannot share mechanisms. Inspect actual implementations or retain
an inconclusive implementation-reuse hypothesis. Do not force runtime properties into
required text fields. Use group_validation and tool_error_feedback for targeted repair;
next_source_reads supplies bounded missing member ranges. Do not repeat an invalid range:
respect indexed file/symbol bounds and tool limits, and read long bodies in chunks.

For callers, cite actual caller_id (file/symbol), implementation_id, relationship_id
and evidence_ids covering the caller body and source declaration anchor (e.g. import).
Use resolved internal edges directed from caller to implementation symbol/file.
These establish static use constraints only, not runtime dispatch or measured costs.

Assess shared_responsibility, meaningful_differences, variation_points, proposed_boundary,
expected_benefit, risks_tradeoffs, migration_complexity, counterevidence_analysis,
rationale, unknowns and limitations. Benefits and migration complexity are qualitative
unless measurements are actually supplied. Never invent savings, timing or scores.
- recommended: strong semantic overlap, plausible low-risk boundary, fully inspected
  implementations AND callers for each, no important unresolved unknowns.
- conditional: useful potential, but important differences or unknowns remain. Explain
  conditions explicitly, including missing caller/contract evidence. Both implementation
  sources must still be inspected. Do not disguise uncertainty as a recommendation.
- not_recommended: similar-looking behavior has distinct semantics, side effects,
  ownership/change reasons or coupling risk. Explain why independence is preferable.
  Limit this conclusion to the inspected proposal, e.g. a base class solely for a trivial
  constructor assignment is not justified. Do not generalize to entire class workflows,
  production behavior or absence of other reuse opportunities from those constructors.

Prefer no finding over weak claims. Rejected comparisons can remain in group_assessments
with not_recommended and no candidate. Positive/conditional candidates link one group_id,
matching classification and the exact member component IDs in components, and cite ALL
assessment implementation/caller evidence. Candidates are design_observation, never
normative violations; legacy modularity_impact describes the reuse/maintenance consequence.
IDs such as REUSE-001 are invocation-local; host stable_id identifies the group across
equivalent snapshots. Use proportional, nonmandatory recommendations, not 'add an interface'.
Set sufficient=false only with specific actionable evidence gaps. A fully inspected
conditional assessment can be sufficient with explicit unknowns and bounded coverage.
Clear resolved missing_information on subsequent passes. Do not infer correctness
solely from having real citations: critically compare semantics and contrary evidence.

For conditional proposals, populate conditions with concrete prerequisites for the
assessed boundary: preserve error/return contracts, mutation ownership, resource cleanup
and any identified differences. Without inspected callers, explicitly mark compatibility
and migration effects unknown, even when the two bodies are fully read. Do not state
guaranteed savings, safe extraction, low effort or identical semantics from similarity.
Keep claims local: mutation of a newly parsed AST is not proof of external shared-state
mutation, and common parsing libraries do not guarantee equal error/dialect policies.
The structural index covers Python, TypeScript and JavaScript, with incomplete symbols
and relations even there. Unindexed behavior or other languages are unevaluated, not absent.
