# ARC-109 — Legacy Migration Strategy

## Rationale

ShopLab Commerce is being restructured incrementally. The existing checkout, orders, inventory, and billing code is preserved for backward-compatibility exercises, while the new quote workflow demonstrates application-owned contracts and explicit adapter wiring.

The existence of older feature packages is not permission to violate ARC-103. A migration plan documents **intent**, not an exemption, and source inspections must judge current implementation independently.

## Target organization

- Domain owns immutable rules and data types, not outbound clients.
- Application owns orchestration and ports for stock, billing and notifications.
- Infrastructure implements inventory persistence, notifications and payment gateways.
- Presentation owns CLI/HTTP and channel-specific rendering.
- Bootstrap provides composition and chooses concrete implementations.

## Proposed migration phases

1. **Characterize behavior:** capture existing order tests and define stable public outcomes.
2. **Declare use-case ports:** introduce interfaces for stock availability/reservation, charge computation and notification.
3. **Move wiring outward:** construct existing concrete adapters in `bootstrap.py`; inject them inward.
4. **Isolate feature internals:** prohibit cross-feature backing-state access; expose documented operations.
5. **Remove circular ownership:** move orchestration to an application use case and eliminate mutually dependent feature imports.
6. **Retire compatibility paths:** preserve public entry points until consumers migrate.

## Migration controls

Each phase should have before/after dependency graphs, functional regression tests, and a conformance report against relevant rule IDs. A file rename, wrapper or disappearing import is not sufficient proof that a dependency violation has been removed.

## Non-goals

No phase above is asserted to be complete merely because it is documented. Developers should avoid changing the old source files without retaining a reference baseline for comparative testing.
