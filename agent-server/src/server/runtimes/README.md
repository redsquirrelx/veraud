# Shared execution runtimes

This package owns reusable execution infrastructure outside concrete agents.

| Package | Responsibility |
| --- | --- |
| `investigation/` | Shared investigator graph, model calls, structured output, provider pacing and provenance validation |
| `coordination/` | Shared coordinator/manager lifecycle, bounded dispatch, collection, accounting and synthesis helpers |
| `repository/` | Read-only snapshots, access policy, tools, telemetry and execution budget enforcement |

Dependencies flow from `server.agents` to `server.runtimes`, then to shared
configuration and services. Runtimes must not import concrete agents, their
registries, prompts or specialized contracts. Agents provide those through hooks
and retain their domain-specific graph topology and policies.

The data-only module `server.agents.schemes.base` is the shared contract boundary
and may be imported by runtimes. It has no agent or runtime dependencies.
`server.agents.schemes.investigator`, `coordinator` and `manager` own category
contracts and maintainability specializations; runtimes must not import those.
Previous `schemas.py` paths re-export canonical classes for compatibility.

Shared configuration belongs to `config.agents`; exclusive configuration remains
in each agent's `config.py`. See [coordination/README.md](coordination/README.md)
for the shared orchestration contract.

## Evidence preflight and closing consistency

Investigators check candidate citations after `evaluate_evidence`, before accepting
model-declared sufficiency. Unknown citations, metadata-only support and failed commit
attribution become concrete `missing_information` and set `sufficient=false`, allowing
the existing graph to return to source inspection within its remaining budgets.
Pending/inconclusive hypotheses also prevent sufficiency. `Hypothesis.evidence_ids`
can identify independent source support for a conclusion; these citations are checked
when supplied and unknown IDs are removed from finalized hypotheses.

Finalization retains partial findings with specific validation codes. Hypotheses with
invalid citations become inconclusive with an explicit host rationale. For older model
responses without hypothesis citations, a failed finding under the same criterion
prevents treating that hypothesis as independently verified. Independently cited valid
hypotheses are preserved. If final validation contradicts an otherwise successful
closure, termination becomes `evidence_validation_failed`, never `sufficient_evidence`.

Commit verification distinguishes `commit_blob_mismatch` from operational failures
such as `git_unavailable`, `git_object_unavailable`, `git_verification_timeout`,
`verification_time_exhausted` and `source_content_unavailable`. A failed attribution
still removes the commit from the affected evidence reference; it does not discard
the snapshot/content hash or pretend that unverified bytes belong to that commit.

Exact Git blob matches use `commit_verification="exact"`. If exact bytes differ,
the verifier reads the committed blob without checkout filters and accepts only
CRLF/LF equivalence, recorded as `commit_verification="line_endings_equivalent"`.
Both forms retain `git_blob_id` and the original audited `content_hash`; the latter
is never replaced with the commit's hash. BOM, whitespace, code changes and lone CR
differences are not normalized. Attribution metadata is retained in findings and
Blackboard evidence. Failed checks use `commit_verification="unverified"`.

The toolset retains host commit checks for the lifetime of its immutable snapshot.
Investigator results and coordinator invocation ledgers use that same cache, including
metadata references. Finding citations reuse the collected references instead of
appending enriched duplicates. The manager still requires exact nested-reference
equality; mismatches report the nested location, reference and differing field names.
A deterministic collection/validation failure blocks automatic reinvestigation of
that child. Bounded, schema-valid coordinator consumption is retained even when its
evidence fails validation; invalid accounting keeps conservative reservation charges.

Descendant toolsets share an atomic retrieved-character ledger. Each successful
delivery charges its serialized size once against the root budget, including repeated
deliveries. Child budgets are no longer divided by `max_invocations` at each hierarchy
level, so unused reservations cannot strand source-reading capacity. Metadata-only
files also produce bounded `next_source_reads` navigation hints for every investigator.

An explicit provider daily-quota rejection ends recovery immediately with
`provider_daily_quota_exhausted`, preserving evidence and deferred-stage diagnostics.
It does not enter exponential retries even if the suggested delay is short, and
coordinator/manager follow-ups cannot restart the same quota-blocked investigation.
Minute pacing cannot replenish a daily quota.

## Liveness and bounded cancellation

HTTP audits always create an absolute wall deadline (`max_wall_time_seconds`) in
addition to active-time accounting. Request scopes also enforce
`provider_request_timeout_seconds`, even when a transport has no native timeout.
`within_deadline` waits only `cancellation_grace_seconds` for cancellation; late
cleanup tasks remain strongly referenced and their exceptions are consumed. A
cancelled scope cannot publish a late investigation/assessment as fresh knowledge.
This is asynchronous isolation, not forced termination of a Python task.

Activity scopes expose snapshot construction, active investigations, provider calls
and client cleanup with stable start timestamps, elapsed time and last real progress.
Pending cancellations remain visible while the audit supervisor is alive. Polling
does not itself update progress. Child completions are collected incrementally and
cached by invocation identity, then reused by the existing graph collection nodes.
The graph topology, final assignment order and one-time usage accounting are retained.

Incremental collection reuses a completed child publication instead of publishing a
supervisor copy over the original. This preserves native tool measurements and
investigator metadata, including partial `model_call_limit` results. Factory children
that have not published still use the collector's fallback publication path.
Genuine conflicts remain strictly rejected as `blackboard_publication_conflict` at
`publish_result`, with record type and differing field names only. Collection retains
valid usage, lets siblings finish and blocks reinvestigation of that deterministic
failure. The original blackboard record is never overwritten.

If provenance is the only outstanding gap, the investigator proceeds to review and
partial finalization with `provenance_unverifiable`, rather than repeatedly reading
an immutable snapshot to repair its attribution. Actionable source/citation gaps
still return through normal investigation routes while budgets permit.

Recovery context contains `evidence_recovery_tasks` per candidate/hypothesis, with
the question, original evidence needs, cited paths, unread source paths and existing
source IDs that can correct a citation without another read. Missing source and
unknown citations request `inspect_source_or_correct_citations`; pure attribution
failures request `report_provenance_blocker`. `remaining_model_calls` and
`remaining_investigation_calls` expose the remaining call allowance and the portion
available before reserving closure. Architectural-boundary prompts require scoped
conclusions and skeptical review of consumers, implementations and composition;
provenance validation itself does not establish architectural semantics.
