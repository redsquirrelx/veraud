# ENG-001 — Development, Build and Test Handbook

## Environment

- Python 3.10 or newer.
- No third-party runtime packages, credentials, cloud account, or database required.
- Editable installation is optional; alternatively use `PYTHONPATH=src`.

## Commands

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m shoplab.app
python -m shoplab.presentation.cli catalog
python -m shoplab.presentation.cli quote --sku BOOK --quantity 2
python -m shoplab.presentation.http_api
```

## Local HTTP manual smoke test

With the WSGI service running, request `GET http://127.0.0.1:8765/health` and `GET http://127.0.0.1:8765/catalog`, then POST `{"sku":"PEN","quantity":2,"zone":"local"}` to `/quotes` with `Content-Type: application/json`.

## Code change conventions

1. Treat `docs/architecture/03-architecture-rules.md` as the normative rule set.
2. Place domain calculations inside `domain/` and use-case coordination inside `application/`.
3. Define outbound capabilities as inward `Protocol`s; implement them in `infrastructure/`.
4. Bind adapters in `bootstrap.py`, not inside use-case or domain logic.
5. Keep external feature dependencies on public APIs, never on their backing dictionaries.
6. Add domain and use-case regression tests for behavior; verify architecture with a separate conformance check.
7. Update the relevant ADR before changing an architectural exception.

## Development constraints

The fixture prioritizes dependency visibility and determinism over throughput and production completeness. Do not treat successful behavior tests as an architectural pass. Do not add evaluator ground-truth material to this source repository.
