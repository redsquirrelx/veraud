# ADR-0004: Public Interfaces for Feature Ownership

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Inventory, orders and billing must evolve independently. If other feature packages depend on mutable internal dictionaries, renaming or replacing those data structures becomes a breaking change.

## Decision

Feature consumers must use documented public module APIs or use-case ports. In particular, inventory backing state remains private to inventory implementation code; public aliases that expose the same mutable object do not provide encapsulation. Feature dependency graphs must remain acyclic.

## Consequences

Hidden implementation detail changes will not require downstream refactoring. The owning feature must provide suitable read and reservation operations; callers cannot work around gaps by accessing private state.
