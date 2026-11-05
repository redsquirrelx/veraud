# ARC-103 — Normative Architecture Rules

**Status:** Approved · **Scope:** code under `src/shoplab/` unless an exception is explicitly specified below.

This document is the authoritative rule set for architecture conformance. A violation is established from **actual code paths** and references, not solely from a package name, generated comments, import search hits, or a test result. Dynamic imports, aliasing, helper functions and forwarding modules do not invalidate a constraint.

## AR-001 — Domain dependency independence

**MUST NOT:** Code owned by `shoplab.domain` depend on `shoplab.application`, `shoplab.infrastructure`, `shoplab.presentation`, or a concrete outbound adapter, either directly or by delegating an infrastructure operation through an outward package.

**MAY:** Use domain-local objects and Python standard-library value types. Define `Protocol` contracts that reference domain concepts. An externally constructed implementation of a domain port is permitted; instantiation of that concrete implementation **inside** domain code is not.

**Why:** A domain policy must survive replacement of storage and transport adapters. An indirection layer does not change the dependency direction when the domain still controls the concrete outward dependency.

## AR-002 — Application use-case independence

**MUST NOT:** `shoplab.application` import concrete `shoplab.infrastructure` or `shoplab.presentation` implementations, construct concrete infrastructure adapters, or use their private storage. Use cases MUST consume application-defined or domain-defined ports and receive implementations through injection.

**MAY:** Import domain entities, rules, and typed request/response models. A protocol may be defined within `shoplab.application` because its ownership is inward-facing.

**Exception:** The sole composition root `shoplab/bootstrap.py` is permitted to import and wire concrete implementations. A module under `application/` is not a composition root merely because it invokes a factory.

## AR-003 — Infrastructure presentation isolation

**MUST NOT:** Infrastructure code import a presentation module, user-interface formatter, WSGI response constructor, CLI parser, or presentation-owned template. Outbound adapters handle transport or storage; presentation code owns channel-specific rendering.

**MAY:** Infrastructure implement application ports and import domain/application data contracts. Reusable rendering contracts should live inward if they are truly channel-independent.

## AR-004 — Explicit composition boundary

**MUST:** Concrete bindings to application ports be assembled in `shoplab/bootstrap.py` (or a future separately approved composition module). Presentation entry points may call `build_services()` but MUST NOT hand-wire low-level adapters in feature or policy logic.

**MAY:** Test code directly instantiate adapters as fixtures. All files under `tests/` are excluded from the production import restrictions but not from functional assessment.

## AR-005 — Inventory public API and ownership

**MUST:** Any production module outside `shoplab.inventory` interact with the inventory subsystem through its public API (`shoplab.inventory` exports) or a documented public port. Private backing state (`inventory._store`, `STOCK`, or replacement storage objects) belongs exclusively to inventory.

**MUST NOT:** External feature code read or mutate the backing dictionary, re-export it under a public-looking name, or wrap direct access in a helper outside inventory. Renaming the backing module, exposing an alias or using `getattr` does not satisfy the rule.

**MAY:** Implementation code inside inventory read its own backing state to implement public operations. Test-only setup is exempt under AR-004.

## AR-006 — No cyclic feature dependencies

**MUST NOT:** Production feature packages `shoplab.orders`, `shoplab.inventory`, and `shoplab.billing` form a cycle in the static **or reachable runtime** dependency graph. The ownership boundary of each package must remain acyclic.

**MAY:** Use the public inventory API from a higher-level order use case. Shared behavior belongs in domain logic or an inward contract; never rely on mutual imports to coordinate business flows.

**Evidence:** Establish both sides of a dependency cycle; a single import alone is insufficient to prove a cycle.

## AR-007 — Adapter state encapsulation

**MUST NOT:** Production code outside an infrastructure adapter directly reach into its mutable private state, e.g. an adapter's `_products`, `_records`, or `_quotes`, even if the caller is another outward layer. Access must go through a declared read model, public service operation, or application port.

**MAY:** The owning adapter manipulate its own data internally; tests may seed a fresh adapter directly if explicitly isolated from production paths.

## AR-008 — Quote workflow contracting

**MUST:** Quote use cases depend only on application ports and domain rules; money values in the new quote pathway remain integer cents. HTTP/CLI parsing and serialization must remain in presentation. Shipping and promotion adapters must be substitutable without changing use-case source.

**MUST NOT:** Treat an in-memory quote as a reserved order or permanent record. Process-local state is an acknowledged capability limit, not architectural nonconformance by itself.

## AR-009 — Documentation-backed verdicts

**MUST:** Findings of *architecture nonconformance* reference at least one of these explicit rule IDs and current source evidence. The documentation itself cannot be used as evidence that code conforms or violates a rule.

**SHOULD:** Mark unsupported general design criticisms as advisory observations. Inconclusive evidence must not be upgraded to a definitive violation or a definitive clean bill.

## Valid dependency examples

- `domain/catalog.py` using `dataclasses` or other pure domain models.
- `application/quote_order.py` accepting `ProductCatalog`, `PromotionCatalog`, and `ShippingRateProvider` protocols.
- `infrastructure/memory_catalog.py` implementing a public application port with private state.
- `presentation/cli.py` calling `build_services()` from the composition root.
- `inventory/api.py` accessing inventory-owned backing state **inside inventory**.

## Rule exceptions

- `tests/**`: can reference concrete adapters or backing state for isolated fixture creation; not proof of production legitimacy.
- `shoplab/bootstrap.py`: approved composition root for adapter construction.
- Python standard-library imports: allowed where used consistent with the layer's responsibilities (domain may use pure date/decimal/dataclass values but SHOULD NOT orchestrate filesystem/network I/O).
- **No blanket exception** applies to legacy package names, private-module renames, nested imports, or aliases.

## Unspecified behavior

This specification does **not** prohibit every dependency between distinct packages, require a specific folder spelling, or classify all concrete types as violations. If a rule does not address a relationship, record an architectural risk or request clarification instead of inventing a requirement.
