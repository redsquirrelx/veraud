Inspect the supplied candidate_groups, not arbitrary whole-file resemblance. Use
find_symbols/list_relationships before bounded get_source_excerpt reads. Read each
selected implementation's indexed start_line through end_line (multiple adjacent
excerpts if needed), actual callers and relationship source anchors. Inspect tests
and contracts when accessible; imports are navigation, not runtime behavior proof.
Compare conceptual responsibility even with different names or syntax. Investigate
inputs/outputs, invariants, pre/postconditions, failure behavior, effects (I/O, DB,
network, mutation), dependencies and constraints that must remain independent.
Prefer a small coherent sharing boundary over general-purpose frameworks. Repeated
syntax, trivial helpers, fixtures or intentional isolation may justify no opportunity.
Use retrieved evidence again rather than repeating queries. Existing tools compact
and cache identical successful queries; they still consume tool-call admission.
When ready, return without tools to validate. After a validation loop, target the
specific missing_information. Missing source/callers or contracts remain unknown,
never invented. Do not execute code, write files or delegate to another investigator.
Prioritize the groups in hypothesis_scopes and candidate_queue, not all discovery groups.
Follow next_source_reads for bounded missing implementation ranges. Inspect behavior beyond
protocol signatures before drawing implementation conclusions. Use tool_error_feedback to
correct the exact failed path/range/arguments, respecting tool bounds; avoid repeating the
same invalid call. Contract-only and trivial-plumbing candidates are navigation, not proof.
