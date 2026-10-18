Perform a skeptical internal review, not a new investigation or a separate reviewer agent.
Classify every candidate exactly once: accepted, rejected or insufficient_evidence. Check
the actual source excerpts, abstraction_assessments, consumers, variation, counterevidence,
coupling and indirection cost, criterion provenance, recommendation and uncertainty.
Do not accept counts, names, genericity or interface existence as evidence of quality.
A single implementation may be entirely justified by a demonstrated contract/test/plugin
boundary. An adapter that translates behavior is not a useless pass-through by default.
Shared utilities need real usage; duplicated code needs compatible change reasons, not
mere textual similarity. Require evidence for alleged concrete implementation leakage.
Recognize beneficial abstractions as info-level observations without certifying global reuse.
Reject unsupported runtime or intent claims. Do not invent findings or citations. A
violation requires an explicit project rule. Insufficient evidence remains unresolved.

Return hypotheses as well as findings, including candidate-free investigations. For every
resolved hypothesis give exactly one hypothesis_id, status (supported or inconclusive),
rationale, assessment_ids, checked_evidence_ids, scope_supported and unverified_claims.
Also return resolution (confirmed, discarded or inconclusive). Recompute this from the
current evidence: an earlier host downgrade may be resolved by repaired valid assessments,
but never bypass missing source, provenance or committed-declaration coverage. Cover all
hypothesis_scopes declarations with assessments of that same hypothesis. Do not select
an unrelated assessment just because it carries the same hypothesis_id. Check all linked
assessment citations, including counterevidence and participants. Scope-supported means
the entire original question is answered: one inspected test module cannot prove a claim
about multiple suites or universal isolation. Mark such claims unverified or inconclusive.
Check the original question, all named declarations and concrete tradeoffs independently
against valid assessments bound to that hypothesis. Cite the checked source IDs. Imports,
counts and self-participants do not establish use or benefit. A missing/invalid assessment,
unread consumer body, incomplete declaration or substituted scope requires inconclusive.
Do not endorse claims such as bulletproof isolation or no coupling without support.
