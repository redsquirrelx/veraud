# ARC-108 — Verification and Testing Strategy

## Testing layers

| Layer | Examples | What it establishes |
|---|---|---|
| Domain | `Product` constraints, `Promotion` cap, `Parcel` rounding | Pure business rule correctness |
| Use-case | Quote validation, discounts, quote storage | Application behavior with injected adapters |
| Inbound adapter | CLI JSON, WSGI 200/201/400/404 responses | Request mapping and serialization |
| Legacy regression | Stock decrement, disallowed order | Existing scenario remains executable |
| Architecture conformance | Documentation rules vs real code | Direction, ownership and allowed dependency relations |

**Crucial separation:** Passing the first four categories does **not** imply that architecture conformance has passed. Functional execution can remain correct when an internal implementation violates intended dependency rules.

## Conformance methodology

1. Pin a repository revision or snapshot and document its hash.
2. Extract **AR-001..AR-009**, and note their explicit exceptions.
3. Reconstruct imports, dynamic references, delegation, symbol ownership and reached backing state.
4. Compare the observed graph to declared rule constraints.
5. Before marking a prior violation as resolved, inspect new indirections or relocated implementations relevant to the original behavior.
6. Record rule ID, paths, lines, proven call relationship, and confidence / missing checks.
7. Report unrelated design advice separately from confirmed conformance violations.

## Evidence requirements

Confirmed findings require a concrete, current code reference; a pure search miss is not proof of absence. For cycles, demonstrate **both** edges. For encapsulation, identify the actual owner of mutable data and show the external read/mutation. For relative or dynamic imports, resolve the target before deciding.

## Reproducibility

Use the same original source snapshot and immutable rule revision. Compare finding identity, status and evidence provenance; do not require verbatim LLM explanation. Repeat cases when assessing agent variance, and distinguish agent errors from provider/network interruptions.

## Golden data access

Evaluation ground truth (if maintained) must remain outside the project supplied to the auditor. A documentation-only evaluation would otherwise leak answer labels to the model. No conformance labels are included in this project's public documentation.
