Skeptically review every candidate exactly once as accepted/rejected/insufficient_evidence.
This is an internal cognitive stage, not delegation. Inspect actual excerpts and group
comparisons: do responsibilities, invariants, effects, failure behavior and caller
constraints support the claimed sharing boundary? Consider intentional isolation,
domain distinctions, fixture/trivial code and independent change reasons. Shape/name
similarity alone is never a reuse recommendation. Question universal helpers and generic
frameworks that transfer complexity or coupling rather than reduce duplication.
Recommended requires inspected callers and no important unresolved unknowns; conditional
must explain conditions and risks. Accepting a conditional observation does not recommend
an immediate refactor. Distinct semantics can justify rejecting even identical syntax.
Benefits/migration risks are qualitative, not measured savings. Reject unsupported runtime,
performance, cost or intent claims. Check source/counterevidence, classification, confidence,
proportionality and citation completeness. Do not add findings or evidence or fill a quota.

Also review every hypothesis, including candidate-free discarded comparisons. Return
hypothesis_id, assessment_group_ids, checked_evidence_ids, scope_supported, resolution
(confirmed/discarded/inconclusive), rationale and unverified_claims. Cover every group in
that hypothesis's immutable hypothesis_scopes and all implementation/caller citations.
An invalid group or missing behavior cannot be overridden by confidence or real citations.
Signature-only contracts do not establish implementation effects, failures or no-reuse;
constructor-only inspection supports only the proposed constructor extraction decision.
Refuse unsupported claims about whole workflows or repository-wide absence of opportunity.

Resolve the ORIGINAL feasibility-of-sharing question, not merely whether implementations
look similar. Set sharing_supported=true only with resolution=confirmed, nonempty
supporting_group_ids and a concrete supported_boundary already assessed and proposed.
Every supporting group needs a valid positive/conditional candidate you accept in this
review. A rejected candidate cannot support confirmation. Another accepted assessed
proposal within the same hypothesis may still support it; do not discard a hypothesis
automatically because one proposal was rejected. An unassessed alternative (e.g. 'maybe
telemetry') leaves that part inconclusive; it cannot rescue a rejected error-policy merger.
Use sharing_supported=false and resolution=discarded when the inspected sharing proposal
is not justified, with no supporting groups. Use null/inconclusive when only similarity
is established or any part needed to answer the original question is unresolved.

Inspect qualified_group_assessments, including host-added unknowns and qualification_notes.
Conditional acceptance is a bounded proposal, never proof of safe extraction or low effort.
Require explicit conditions preserving return/error contracts, mutation/ownership and
cleanup semantics. Without inspected callers, compatibility and migration remain unknown.
Distinguish freshly created AST mutation from externally shared state; caching or sharing
an AST requires separate justification. Do not claim 'identical', 'pure', 'straightforward'
or guaranteed benefit merely because the same library or algorithm appears in both bodies.

Structural representations cover Python, TypeScript and JavaScript. They are incomplete
even within those languages; missing indexed consumers/edges do not prove no consumers,
no effects or no opportunities. Do not assume structural coverage for other languages.
