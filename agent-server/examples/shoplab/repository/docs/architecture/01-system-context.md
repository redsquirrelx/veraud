# ARC-101 — System Context and Scope

**Status:** Approved · **Scope:** current demonstrator and intended production boundaries.

## Business purpose

ShopLab Commerce supports a small retailer handling product availability, order acceptance, billing, promotions, and shipment quotes. A retail clerk or integration client can request catalog information and an order quote. An operator can use a local CLI; a developer can exercise the development HTTP interface. The preserved legacy checkout demonstrates order reservation and confirmation.

## Actors and external systems

| Actor/system | Interaction | Current realization |
|---|---|---|
| Checkout client | Requests price/availability quote | CLI or HTTP JSON |
| Operations staff | Inspect product catalog and run demos | CLI |
| Stock management | Tracks stock levels and reservations | Legacy in-memory inventory |
| Promotion service | Provides promotion definitions | In-memory development adapter |
| Carrier rate service | Supplies delivery prices | Deterministic table adapter |
| Notification service | Delivers order messages | Console demonstration adapter |
| Persistence | Stores quotes and stock state | Process-local memory only |

External providers in the table are **logical ports**. Their presence does not imply this repository connects to a real cloud service, gateway or database.

## Bounded responsibilities

- **Catalog:** current product properties, activation and prices.
- **Quoting:** validation and composition of product, promotion and delivery costs.
- **Orders:** acceptance of a legacy order command.
- **Inventory:** stock reads and stock reservation, owned by the inventory feature.
- **Billing:** calculation of legacy charges and receipts.
- **Notifications:** rendering and delivery via replaceable interfaces.

## Non-goals

No real payment capture, persistent database, authentication, concurrent reservation guarantees, fulfillment partner integration, tax calculation, or production authorization model are implemented. In particular, a successful local quote is not a promise of stock reservation.

## Architecture drivers

1. Decouple business rules from transports and storage mechanisms.
2. Make architectural responsibilities and dependency constraints auditable.
3. Support tests without network access or third-party services.
4. Keep the legacy entry points functional while new functionality is introduced.
5. Replace adapters without revising domain or use-case logic.
