# ShopLab Commerce Architecture Specification

| Property | Value |
|---|---|
| Document ID | ARC-000 |
| Revision | 1.0 |
| Status | Approved for architecture-conformance exercises |
| System | ShopLab Commerce |
| Audience | Maintainers, architects, QA, automated audit tooling |
| Architectural approach | Clean Architecture with an incremental legacy transition |
| Runtime | Python 3.10+, single process, in-memory development adapters |

## Purpose and interpretation

This specification records **intended architecture**. The repository includes both existing modules and modules implementing a newer quoting workflow. Architecture rules define what implementations *should* respect; do not assume a rule is already satisfied just because it appears in this document. Normative requirements use **MUST**, **MUST NOT**, **SHOULD**, and **MAY** in their conventional engineering sense.

Each detected nonconformance must cite: a rule ID, its normative source, the relevant current source path(s), and evidence showing the disallowed relationship. The absence of a familiar import string is not sufficient evidence of compliance if a relevant helper, facade, export or dynamic call exists.

## Documents

1. [System context](architecture/01-system-context.md) — actors, responsibilities, scope and integrations.
2. [Component model](architecture/02-component-model.md) — layers, package ownership, dependency direction.
3. [Architecture rules](architecture/03-architecture-rules.md) — **normative source of truth** for code boundaries.
4. [Runtime and data flows](architecture/04-runtime-data-flows.md) — important execution paths and data handling.
5. [Quality attributes](architecture/05-quality-attributes.md) — maintainability, security, operability.
6. [Interfaces and contracts](architecture/06-interfaces-and-contracts.md) — ports and interaction rules.
7. [Deployment and operations](architecture/07-deployment-operations.md) — execution environments, limitations.
8. [Verification and testing](architecture/08-verification-testing.md) — how to demonstrate conformance.
9. [Migration strategy](architecture/09-migration-strategy.md) — legacy coexistence and planned separation.
10. [Architecture diagrams](diagrams/README.md) — context, modules, and sequences.

Related material: [ADRs](adr/README.md), [API specification](api.md), [engineering handbook](development.md), [glossary](glossary.md).

## Evidence priority

1. Explicit constraints with stable rule IDs in `architecture/03-architecture-rules.md`.
2. Accepted ADRs, when they clarify or narrow a rule.
3. Defined interface contracts and ownership responsibilities.
4. The actual implementation and runtime call graph (facts about what code does, **not** authority about what it should do).
5. General design principles only as advisory risks, never as a substitute for undocumented project-specific prohibitions.

In case of conflict, report the conflicting documents rather than silently inventing a rule. These documents deliberately avoid enumerating actual nonconformances; discovering them is a verification activity.
