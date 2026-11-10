# ARC-105 — Quality Attribute Scenarios

## Maintainability

**M-01 Modularity:** A new carrier tariff can replace `TableShippingRates` by implementing `ShippingRateProvider`, with changes confined to its adapter and composition root. Observable evidence: no import of concrete carrier classes inside domain or quote use case.

**M-02 Analyzability:** An engineer can answer which module owns an operation and cite a stable architecture rule for prohibited dependencies. Observable evidence: source references for both the documentation rule and the violated import/call path.

**M-03 Modifiability:** In-memory catalog can be replaced with a database-backed adapter without edits to `domain/catalog.py` or `application/quote_order.py`. Tests may inject a fake catalog through the same port.

**M-04 Testability:** Business rules are executable in pure unit tests; application use cases accept injected fake implementations. The test suite uses no live payment or carrier service.

**M-05 Reusability:** `Promotion.discount_for` can be used by a CLI or HTTP workflow without dependency on the presentation channel.

## Security and privacy

**S-01 Data minimization:** Quote responses expose only the minimal fields required for pricing; there is no customer PII in the present workflow.

**S-02 Input validation:** Quantity, SKU, zone and JSON payload sizes must be validated before invoking downstream adapters. These controls are suitable for a *local demonstrator only*.

**S-03 Trust boundaries:** No production credentials or network-access credentials may be embedded in source. Future production deployment needs authentication, authorization, TLS termination and rate limiting, none of which are supplied here.

## Performance and operational behavior

**P-01 Predictability:** Local quote computation should require a bounded number of port calls, independent of unrelated inventory items.

**P-02 Determinism:** Given a fixed catalog, promotion and tariff, the computed monetary amounts are deterministic. Quote identifiers are intentionally non-deterministic.

**O-01 Observability:** Developer errors should be reproducible with the reported CLI command and test case. No production telemetry/alerts are included.

## Measurement caveat

These are quality scenarios, not automatically passed nonfunctional tests. A conformance agent should not claim that mere existence of documentation proves the corresponding code behavior.
