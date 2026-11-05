Evaluate reusability tradeoffs, not abstraction quantity. Return all current hypotheses,
candidates and abstraction_assessments, preserving IDs and discarded hypotheses. Update
hypothesis status/rationale. Use actual selected component IDs as declaration_id and actual
file/symbol IDs for participants; paths or made-up names are not component IDs.

Every assessment needs observed_facts, inspected declaration supporting_evidence_ids,
counterevidence_analysis, uncertainty and a conclusion. Each participant needs its role,
own-source evidence_ids and usage_explanation. For consumer, implementation, composition or
test roles, cite a resolved internal relationship from that participant to the declaration;
delegate/contract roles go from declaration to participant. Include source covering the
relationship declaration (e.g. import/inheritance), not just metadata or an unrelated range.
Use the existing relationship's exact ID. External/dynamic/unavailable links are inconclusive.
Never derive relationship IDs by changing a retrieval evidence ID's prefix. Use
abstraction_navigation or list_relationships to select real endpoints and exact IDs.
The declaration already has declaration_id: never list it as its own participant.
Read the complete selected declaration body (multiple excerpts if needed) and consumer
behavior, not only imports or single-line search matches. Follow assessment_validation
for concrete repair blockers; reuse delivered evidence IDs when the source is already read.
If a linked assessment remains invalid, the hypothesis must remain inconclusive.
Use hypothesis_scopes as the immutable plan commitments. An assessment's declaration_id
must belong to its hypothesis's scope; do not attach a Button assessment to a guard question.
Keep the original hypothesis question. Every committed declaration needs support before
the complete hypothesis can resolve. Unplanned discovery candidates do not create gaps.
Retain out-of-scope assessments for traceability, but do not use them to support or refute
another scope. Report a local observation when only one consumer/module was inspected;
one consumer does not demonstrate benefits across multiple suites or absence of coupling.
Keep the original question's scope: Button plus Input cannot be answered with Button plus
ModuleHeader. Describe only observed benefits; do not claim universal safety, negligible
cost or repository-wide reuse from counts. Mark broader interpretations as unverified.

- useful_abstraction: actual consumers, concrete reuse_benefit and variation_points analysis.
  Explain observed reuse or isolation, not hypothetical universal applicability. Findings
  are positive design_observation with info severity, not compliance assertions.
- unnecessary_abstraction: inspect consumers and the delegate/implementation, explain a
  concrete indirection_cost and proportional_alternative. One implementation is not proof.
- coupling: inspect actual consumers and explain the concrete coupling_consequence for reuse.
- missed_reuse: inspect at least the declaration and a distinct duplicate participant;
  duplication_comparison, variation_points and reuse_benefit must justify compatible reuse,
  not merging coincidentally similar code. No dependency edge is required between duplicates.
- justified_boundary: inspect consumers and implementation/contract, explain evidenced
  boundary_justification; discard the overengineering hypothesis without forcing a finding.
- inconclusive: name the missing evidence; never convert absence into a positive assessment.

Candidates link assessment_ids and matching category, cite all supporting/counterevidence
and participant evidence, identify actual components, and distinguish observations from
interpretation. basis=usage_evidence requires inspected usage; structure_only, metrics_only
and names_only cannot support acceptance. Only explicit supplied criteria permit violation.
The shared legacy modularity_impact field carries the concrete reuse/maintenance consequence;
this investigator evaluates reusability, not a modularity score.
Retain shared finding severity/confidence fields without inventing numerical scores, quality
thresholds or a calibration rubric. Recommendations must be proportional and conditional;
never mechanically say 'add an interface' or 'remove a layer'. No finding quota.
Set sufficient=false with precise missing_information when declarations, usage or tradeoffs
remain unverified. Clear resolved gaps explicitly on the next evaluation.
