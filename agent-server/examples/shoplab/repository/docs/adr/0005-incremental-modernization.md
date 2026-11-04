# ADR-0005: Incremental Modernization of Legacy Checkout

- **Status:** Accepted
- **Date:** 2026-10-25

## Context

The original ShopLab checkout has existing behavioral tests and active package interfaces. Replacing it wholesale would invalidate regression evidence and obscure architecture changes.

## Decision

Keep the existing checkout API operational while introducing new use cases and adapters incrementally. Record target dependencies in ARC-103 and migration stages in ARC-109. Legacy origin does **not** exempt a dependency from current architecture constraints.

## Consequences

New functionality can demonstrate clean separation without interfering with existing workflows. The repository must be analyzed for both conforming and nonconforming relationships rather than assuming a perfectly migrated structure.
