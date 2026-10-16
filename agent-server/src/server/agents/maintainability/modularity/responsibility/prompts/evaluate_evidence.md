Evaluate responsibility cohesion, separation, placement and heterogeneous accumulation
using observed behavior and the supplied criteria. Treat these as investigation lenses,
not universal rules, normative size thresholds or automatic ISO noncompliance.
For each inspected component return component_assessments with an actual file/symbol
component_id from tools. List inferred responsibilities, concrete behaviors, plausible
independent change reasons, supporting and contradicting delivered evidence IDs.
Explain potentially_incompatible responsibility groups with their IDs, why their change
reasons are independent and the concrete maintenance risk. Assess cohesion as coherent,
mixed or inconclusive, and consider architectural justifications for grouping behavior.
Names, size, method counts and dependency counts alone establish neither low nor high
cohesion. A large cohesive class or a service orchestrating one coherent business purpose
can justify discarding a hypothesis. Never manufacture a finding to fill a quota.
Candidates must link assessment_ids, cite the inspected source supporting the attributed
behaviors, and explain a concrete modularity impact and the benefit/cost of separation.
Set basis=behavioral only for behavioral evidence; metrics_only/names_only candidates
cannot be accepted. Do not recommend fragmentation without an expected maintenance benefit.
Only explicit supplied project criteria can justify kind=violation. Design-principle or
inferred criteria permit only design_observation. Never invent a rule or a citation.
Retain all previous hypotheses and assessments across iterations, including discarded
and inconclusive investigations. Return all current candidates, not only new ones.
If relevant behavior or caller evidence is missing, sufficient=false and precise
missing_information must guide the next investigation. An empty candidates list is valid.
