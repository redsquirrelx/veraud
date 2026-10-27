# Functional adequacy

`agent.py` owns the direct four-node graph (`prepare → code_mapping → verify → build_results`).
`schemas.py` defines requirement, fragment, evidence and result contracts; `repository_adapter.py`
selects code fragments for snapshot-backed audits; `audit.py` publishes findings/evidence to
the shared Blackboard. Prompt files are local to this package.

Retrieval uses cached SentenceTransformer embeddings and `util.cos_sim`; verification is a
separate LLM step. Preserve retrieval top-k, deterministic ordering, the explicit `app.get`
hint, CPU offloading with `asyncio.to_thread`, and the insufficient-evidence fallback. A
similarity score does not itself establish functional compliance.

See [`../../../../docs/architecture.md`](../../../../docs/architecture.md) for ownership and
[`../../../../docs/contracts.md`](../../../../docs/contracts.md) for HTTP/workflow contracts.
Focused tests: `tests/test_functional_adequacy.py`,
`tests/test_functional_adequacy_repository_adapter.py` and
`tests/test_functional_adequacy_integration.py`. The direct SBERT test may require cached
weights; do not trigger a download implicitly.
