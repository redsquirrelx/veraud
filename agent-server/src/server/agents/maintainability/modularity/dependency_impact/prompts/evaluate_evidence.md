Evaluate whether inspected dependencies create maintenance harm, not merely whether they
exist. Return dependency_assessments for actual investigated relations and impact hypotheses.
Each assessment links hypothesis_id. Each dependency uses real source_id/target_id and
relationship_id from repository tools, and the EXACT graph dependency_type (for example
from_import, not calls inferred from an import). Citation evidence_ids must include the
actual declaration lines AND source inspection of both endpoints. A missing static edge
can use relationship_id=null and impact_kind=inconclusive, recording the limitation.
Optional dependency_path lists ordered component IDs; each hop must appear in dependencies,
with at most dependency_limits.max_depth hops and max_relationships_per_assessment edges.
A path proves structural reachability only; explain each relevant contract boundary before
attributing propagation. A cycle or shared dependency is not inherently a maintenance defect.
Explain contract_analysis, architectural_justification, change_scenario, consequence and
propagation_explanation using actual observed usages and possible alternative designs.
Use supporting_evidence_ids from source at all relevant endpoints, and separately cite
contradicting evidence. Interface presence/absence and coupling counts alone prove nothing.
impact_kind=demonstrated requires actual evidence for the consequence and a separate
demonstration_rationale plus demonstration_evidence_ids; a hypothetical provider replacement
is normally plausible_risk, not an observed historical cascade. Retain uncertainty and
limitations. Use none for a justified dependency without substantiated harm, inconclusive
for missing evidence, and discard hypotheses when counterevidence warrants it.
Candidates link assessment_ids and all citations underpinning the relation and consequence.
Only basis=consequence_evidence can support a finding; metric/cycle/transitivity/interface
or existence-only claims are insufficient. Describe concrete maintenance impact and a
proportionate recommendation; do not demand unnecessary interfaces or decoupling.
Only explicit supplied project criteria justify kind=violation; design heuristics and
inferred conventions permit only design_observation, never automatic ISO noncompliance.
Return all current candidates, hypotheses and retained assessments, not only new ones.
Missing relevant evidence means sufficient=false with precise missing_information for
another tool investigation. Empty findings and legitimate dependencies are valid results.
