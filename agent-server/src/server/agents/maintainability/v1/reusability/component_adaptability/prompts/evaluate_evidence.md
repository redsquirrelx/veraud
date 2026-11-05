Return AdaptabilityEvaluation with all hypotheses, candidates, constraint_assessments,
cleared_components and coverage_rationale. Preserve prior hypothesis IDs and update their
status/rationale. Keep original questions and hypothesis_scopes fixed; evidence for another
component cannot confirm this question. Every planned component needs an inspected assessment or an explicit
source-backed clearance with no finding; do not manufacture defects to fill a quota.

Each ConstraintAssessment has stable id, actual selected component_id, hypothesis_id,
constraint_type and a precise constraint_key identifying the same root constraint across
files (e.g. "database:fixed-production-endpoint", not simply "coupling"). State observed
facts separately from adaptation_impact inferences; adaptation_effort is qualitative,
never an invented hour/cost estimate. Record assumptions, unknowns and limitations.
Compare actual dependency use and representative instantiation/configuration against the
target context, examining mitigating seams and counterexamples before asserting rigidity.

supporting_evidence_ids must cover the complete indexed component body, not a name,
metadata record, lone declaration line or unrelated source. Include inspected global/
import/config locations in supporting/counterevidence where relevant. seam_analysis and
seam_evidence_ids must include inspected component source showing constructor/public
boundary/configuration behavior; include actual external factories/adapters as additional
source when relevant. Absence in a bounded search is not proof no override exists anywhere.
Reassess prior conclusions against ALL accumulated source reads, including automatic
body continuations. constraint_validation.evidence includes host-attached continuations
for an already source-cited component; these establish inspection coverage, not semantic
support or a confirmed obstacle. Update facts, seams, counterevidence and conclusions
when later excerpts change the interpretation; do not merely repeat the initial excerpt.
For usage, cite caller_id (real file/symbol), resolved internal relationship_id directed
from caller to component symbol/file, and evidence_ids covering caller body plus relationship
source anchors (e.g. import). Explain instantiation_configuration. Static edges alone do
not establish invocation, mandatory dependence or runtime side effects.

Conclusions:
- verified_obstacle: explicit input target_context, assessed_context exactly matches it,
  context_basis="explicit"; body/seams AND representative usage inspected; no important
  unresolved unknowns. Explain why the target is incompatible and current seams insufficient.
- context_dependent_risk: evidence-backed constraint whose adaptation impact depends on
  assumptions or unknowns. If target_context=null, context_basis="plausible" and explicit
  nonempty assumptions; a hypothesized context is NOT a user requirement. If an explicit
  target exists, use it exactly. Missing usage or wider override knowledge is qualified.
- mitigated: observed injection/configuration/adapter seam disproves the suspected rigidity;
  cite the seam and discard the unsupported hypothesis. No negative candidate is needed.
- unknown: insufficient evidence, explicitly identify the blocker. No accepted defect.

Candidates are design_observation, not normative violations. Link matching assessment_ids,
constraint_type and classification (verified_obstacle/context_dependent_risk), use the
exact component IDs and cite ALL linked supporting, counter, seam and usage evidence.
One candidate may combine the same root constraint across files only when constraint_key,
type and assessed_context agree. Host stable_id preserves root-constraint/context identity;
original candidate IDs remain for review history. The legacy modularity_impact field holds
the reusability/adaptation consequence. Recommendations/mitigation_options are optional,
proportional possibilities, not generated refactors or mandatory abstraction changes.

Set sufficient=false with a targeted next evidence step only when that step can resolve
the uncertainty; an unverifiable conclusion remains unknown. Set can_investigate_further=false
with a concrete continuation_reason when necessary evidence cannot be obtained with the
available tools (e.g. an external deployment contract); the host finalizes limited output
without pointless retries. Otherwise leave can_investigate_further=true and name the
targeted next inspection in missing_information. Clear resolved gaps on a
later pass. Fully qualified context-dependent assessments can complete without pretending
all unknowns are resolved. cleared_components requires complete body inspection and a
concrete coverage_rationale, never a blanket certification of portability.

When genuinely blocked, set continuation_blocker to external_context, unavailable_source
or dynamic_behavior and explain the specific missing fact in continuation_reason. 'Enough
evidence collected' is not a blocker. Missing available bodies, mismatched component IDs,
citations or seam checks are repairable: keep can_investigate_further=true and use
next_source_reads, constraint_validation and candidate_validation for targeted repair.

For data_schema, set schema_dependency_basis and schema_adaptation_analysis. Distinguish
the expected metadata INPUT SHAPE from fixed DOMAIN VALUES. Explain the specific mismatch
with the assessed context and why existing function parameters, mappings or adapters do
not already handle it. A fixture with named tables does not establish those table names
are hardcoded in production. fixture_only/unknown cannot establish a production obstacle.
Do not infer lack of seams from absence of an abstract interface: dictionaries or parameters
can themselves be effective seams. Keep unknowns if data provenance/configuration is unread.
An input_contract risk requires inspected representative usage/input preparation, not
only key lookups in the component. Explain why translating supplied data cannot already
meet that contract; otherwise retain an unknown or mitigated assessment without a candidate.
Do not combine assessments with distinct constraint_key, assessed_context, type or
classification into one candidate. The host splits such mixed candidates, preserving the
original in candidate_split_history; use the current candidate IDs for subsequent work.
