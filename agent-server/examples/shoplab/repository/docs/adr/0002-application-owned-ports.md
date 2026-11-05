# ADR-0002: Application-Owned Ports

- **Status:** Accepted
- **Date:** 2026-10-17
- **Deciders:** Commerce engineering

## Context

Quote calculation needs product, promotion, shipping-rate, ID and quote recording services without committing the use case to their storage and transport mechanisms.

## Decision

Define `ProductCatalog`, `PromotionCatalog`, `ShippingRateProvider`, `QuoteRecorder`, and `QuoteIdFactory` as `Protocol`s in `application/contracts.py`. Inject implementations into use cases. Concrete bindings are performed in `bootstrap.py`.

## Consequences

Unit tests can substitute fakes without network or database access. Adapters must track the published contracts. This is not a blanket license for application code to instantiate infrastructure classes.

## Alternatives

Importing adapters directly from use cases was rejected due to tight coupling. Keeping port definitions inside infrastructure was rejected because it reverses ownership of application contracts.
