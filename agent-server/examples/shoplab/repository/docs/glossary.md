# GL-001 — Architecture Glossary

- **Architecture conformance:** degree to which an implemented system respects its declared architecture and restrictions.
- **Clean Architecture:** design approach that keeps business policy independent from infrastructure and delivery mechanisms, with source dependencies pointing inward.
- **Domain:** stable business concepts and rules without knowledge of adapter implementations.
- **Use case:** application-level operation orchestrating domain rules and explicit ports.
- **Port:** interface describing a capability required by an inward layer.
- **Adapter:** concrete implementation or transport translation at a system boundary.
- **Composition root:** controlled location where concrete implementations are constructed and injected.
- **Backing state:** mutable internal data structures owned by an adapter or feature module.
- **Public subsystem API:** approved operation or interface through which other modules interact with a subsystem.
- **Dependency cycle:** mutually reachable package imports/calls violating acyclic ownership rules.
- **Architectural violation:** an observed dependency or data flow that contradicts an explicitly stated rule.
- **Advisory risk:** a design concern not established as a documented architecture nonconformance.
- **Snapshot evidence:** path and source span from the specific inspected code revision.
