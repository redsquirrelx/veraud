# ShopLab Commerce — Architecture and Developer Guide

**Document set:** Version 1.0 · **Status:** Approved architecture specification for the test system · **Language:** English.

ShopLab Commerce is a runnable, dependency-light Python commerce backend used to exercise a software architecture conformance process. It includes a legacy order-processing pathway and a newer quote-order workflow developed with Clean Architecture principles. The architecture **specification** describes intended boundaries; it is not a certification that every implementation conforms.

## Quick start

Python 3.10+ is required. From the repository root:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m shoplab.app
python -m shoplab.presentation.cli catalog
python -m shoplab.presentation.cli quote --sku BOOK --quantity 2 --zone local --promotion WELCOME10
python -m shoplab.presentation.http_api
```

No third-party runtime dependencies or external services are needed. The optional HTTP server binds to `127.0.0.1:8765`; it is a demonstrator, not production infrastructure. All monetary values in the new workflow are integer cents. The legacy checkout uses its pre-existing integer price representation and state.

## Documentation entry points

- [Architecture specification](docs/architecture.md) — authoritative navigation and definition of terms.
- [Dependency and boundary rules](docs/architecture/03-architecture-rules.md) — normative, stable rule IDs and explicit exceptions.
- [System and component views](docs/architecture/02-component-model.md) — Clean Architecture structure and ownership.
- [Runtime and data flows](docs/architecture/04-runtime-data-flows.md) — sequence diagrams and storage behavior.
- [Decision log](docs/adr/README.md) — accepted architecture decisions with rationale.
- [Development and verification](docs/development.md) — commands, constraints, test levels.
- [API contract](docs/api.md) — CLI and development HTTP interface.

## Repository layout

```text
src/shoplab/
  domain/          Enterprise rules, value objects, existing domain contracts
  application/     Use cases, application-owned ports and DTOs
  infrastructure/  Concrete data, ID, pricing and transport adapters
  presentation/    CLI, WSGI and view-formatting adapters
  bootstrap.py     Composition root; explicit adapter wiring
  billing/         Legacy billing feature package
  inventory/       Legacy inventory feature package and its public API
  orders/          Legacy order processing feature package
  app.py           Preserved legacy demo entry point
docs/              Normative architecture and implementation guidance
tests/             Black-box and domain tests (not conformance tests)
```

The legacy baseline source files and existing legacy tests remain unchanged. The new capability is additive. The project intentionally exercises conditions where an implementation must be *compared* against architecture documents, rather than assuming documented aspirations are already implemented.

## Evaluating architecture

A conformance tool should: (1) extract explicit rules and exceptions from the documentation; (2) inspect real imports, call paths, and data access in the selected source snapshot; (3) supply file/line evidence; (4) distinguish confirmed violations from inferred design risks and cases of insufficient evidence. Passing functional tests alone does not prove architecture conformance. Evaluation ground truth is stored **outside this repository** by the test owner.
