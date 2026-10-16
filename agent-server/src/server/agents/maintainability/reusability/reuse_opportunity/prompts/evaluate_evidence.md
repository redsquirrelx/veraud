Return ReuseEvaluation: all hypotheses, candidates, group_assessments and precise
missing_information. Preserve stable group IDs and prior hypotheses; update their
status/rationale. Assess every selected group, or identify its evidence blocker.

Each group assessment names exactly the two selected component IDs and compares
their purpose, inputs_outputs, preconditions_postconditions, failure_behavior,
side_effects, dependencies and invariants. Cite delivered evidence_ids covering
each entire indexed implementation; a declaration, name, count or metadata is not
proof. Distinguish observed facts from inference in each explanation. Unknown
behavior is explicitly unknown, not assumed pure/equivalent. Unknown citation IDs
or invented locations cannot support conclusions.

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
