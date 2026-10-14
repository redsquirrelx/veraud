Critically review every dependency-impact candidate exactly once as accepted, rejected
or insufficient_evidence. Do not paraphrase or accept all findings automatically.
Check actual relation IDs, endpoints, declaration/source excerpts and the claimed kind.
An import does not prove runtime invocation; a path or cycle does not prove change
propagation. Verify what contract/detail consumers rely on and why a specified change
would force an independent component modification. Question speculative consequences,
frequency claims, metric-only conclusions, missing counterevidence and generic coupling
slogans. Distinguish demonstrated effects from plausible scenarios and uncertainty.
Consider stable contracts, intentional co-evolution, encapsulation, alternatives and the
cost of extra abstractions. Interfaces can leak details; their absence is not a defect.
Check source evidence at both endpoints, criterion scope, maintenance impact, severity,
confidence and whether recommendations avoid needless decoupling. Never turn an inferred
design principle into a documented project rule. Reject false positives or downgrade
incomplete support; do not add new findings/evidence. Record investigation limitations.
