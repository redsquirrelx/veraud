# ADR-0001: Adopt Clean Architecture

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** Commerce engineering and architecture working group
- **Applies to:** All production source under `src/shoplab/`

## Context

ShopLab needs stable business rules while external gateways, persistence and inbound channels change. Unrestricted package dependencies make feature evolution costly and reduce the value of isolated tests.

## Decision

Use domain, application, infrastructure, presentation and one explicit composition root. Source dependencies point inward. Infrastructure implements application-owned ports. Channel-specific formatting stays in presentation. Detailed constraints and any exceptions are authoritative in ARC-103.

## Consequences

Application logic can be tested with fakes; backend adapters remain replaceable. The additional interfaces and composition code are justified by expected change. Existing code may require migration; adoption of an ADR does not guarantee immediate conformance.

## Alternatives considered

A single service module was simpler but harder to substitute and audit. A full microservices split added deployment overhead with no business requirement. A module-first monolith with Clean Architecture was selected.
