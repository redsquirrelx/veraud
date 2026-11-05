# ADR-0003: In-Memory Development Adapters

- **Status:** Accepted for the training demonstrator
- **Date:** 2026-10-20

## Context

Architecture experimentation needs a fast, portable fixture with deterministic prices and no external credentials or infrastructure.

## Decision

Keep catalog, promotions, carrier-rate tables, quote storage, and legacy stock in local Python structures for development. Preserve replaceability through contracts. Do not represent this implementation as production persistence.

## Consequences

Easy local execution and repeatable tests. No multi-process persistence, recovery, concurrency guarantees, idempotent payment operations or backup. Production adoption would require hardened adapters and operations controls.
