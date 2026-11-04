# ARC-106 — Interface and Contract Registry

## General guidance

Inward-facing use-case ports are defined in `shoplab.application.contracts`; concrete implementations are composed in `shoplab.bootstrap`. Contracts use native Python typing and explicit data objects. The adapter may use SQL, HTTP or memory in a future build, but none of those choices belong in a port type signature.

| Interface | Operation | Defined in | Current adapter |
|---|---|---|---|
| `ProductCatalog` | `get(sku)` / `list_active()` | Application | `MemoryProductCatalog` |
| `PromotionCatalog` | `find(code)` | Application | `MemoryPromotionCatalog` |
| `ShippingRateProvider` | `price_cents(parcel)` | Application | `TableShippingRates` |
| `QuoteRecorder` | `save(quote)` / `get(quote_id)` | Application | `MemoryQuoteRecorder` |
| `QuoteIdFactory` | `new_id()` | Application | `UuidQuoteIds` |
| `Notifier` | `send(order, message)` | Domain (legacy contract) | `ConsoleNotifier` |

## ProductCatalog

Returns `Product | None` for a unique SKU and `tuple[Product, ...]` for active products. Clients do not get or require the adapter's underlying mutable dictionary. No global order is mandated beyond the current development adapter's SKU sort order.

## PromotionCatalog

Promotion lookup is code based. Discount computation is owned by `domain.promotions.Promotion`, not by the transport adapter. A missing promotion is a use-case validation error.

## ShippingRateProvider

Consumes a `Parcel` value object and returns nonnegative integer cents. A carrier's API schema and authentication are private implementation concerns, not part of the application contract.

## QuoteRecorder and QuoteIdFactory

`StoredQuote` is an immutable application contract. `QuoteRecorder` creates a per-runtime record and provides lookup; retention guarantees are absent. `QuoteIdFactory` abstracts unique ID creation from the use case.

## Public legacy inventory API

`shoplab.inventory.available_stock(sku)` returns an integer count. `shoplab.inventory.reserve_stock(sku, count)` attempts a stock decrement and returns a boolean. These functions are the subsystem's public access boundary (AR-005). External consumers must not require a particular backing store implementation or bypass these functions with raw storage references.

## Interface evolution

Port signature changes require corresponding adapter and contract-test updates. Adding a concrete adapter does not authorize changing layer dependency rules. Architecture exceptions require a new ADR and a revision to ARC-103.
