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
Every confirmed/discarded hypothesis must cite relevant source and link to an assessment
for that exact question. Discarding requires impact_kind=none backed by verified relations
and inspected contracts/usages at both endpoints, not absence of discovered edges.
Directory names, manifests, imports, schema metadata and evaluation gold datasets cannot
prove HTTP-only communication, replacement independence or absence of change propagation.
Search-hit single lines are navigation: retrieve the relevant implementation bodies and
contracts before making causal claims. An HTTP boundary may still carry schema, protocol,
configuration or shared-data coupling. Do not infer isolation from separate runtimes.
Endpoint IDs must be actual file/symbol IDs, never package/directory paths. If host feedback
reports invalid IDs, repair them from delivered tool records before more broad searching.
Keep unsupported global questions inconclusive and state the specific missing reads.
Never invent dependency_type="none" or a manifest-to-server edge to represent absence.
If no actual relation was established, leave dependency_assessments empty for that question
and its hypothesis inconclusive; the nonempty dependencies contract applies only to an
assessment you actually produce. Positive packaging/isolation claims are not harm findings.
When closure is due to token budget, evaluate only delivered evidence and retain gaps.
