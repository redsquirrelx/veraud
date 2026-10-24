# Boundary investigation: scope, coverage and continuation

The boundary investigator retains the existing plan → investigate/tools → evaluate
→ review → finalize graph. Token-unlimited mode does not remove its call, time or
`max_iterations` limits. Reaching a limit produces a partial result with concrete
`investigation_tasks`; it never certifies the remaining scope.

## Claims and their evidence

- Package manifests support a scoped packaging declaration, not service isolation.
- Dependency evidence must show actual imports; follow targets to determine whether
  they implement HTTP calls, persistence, formatting or other behavior.
- Behavior checks require delivered bodies of the named functions/methods.
- Isolation requires implementation, usage and composition, plus separate
  `verifications` for dependency direction, shared resources and composition.
- Independent-deployment claims additionally require `claim_kind=deployment` and
  a deployment verification citing relevant deployment configuration.

The host checks cited ranges, named component scope, neighbouring dependencies,
unresolved edges and the consistency of claim type with conclusion wording. A
`coverage_complete` flag cannot replace those checks. Conservative wording checks
only withhold unsupported conclusions: they are not a natural-language theorem
prover. Independent semantic review still checks the actual operations, architectural
context, counterexamples and the content of each verification. A concrete
counterexample can disprove a broad hypothesis without an exhaustive absence proof.

## Work selection and metrics

`investigation_tasks` prioritizes unresolved hypotheses and concrete dependency
endpoints. Suggestions are navigation, never additional evidence. Search-hit lines
are distinguished from actual `get_source_excerpt` deliveries. Coverage reports
excerpt files, fully delivered files, unique source lines and dependency pairs with
both endpoints inspected. None of these counts alone proves architectural compliance.

If the model closes a renewed investigation with concrete reads pending, the host
can request one batch of at most two missing ranges through the existing ToolNode
before evaluation. Normal tool budgets, access checks and accounting apply. Already
delivered chunks are skipped; citation-only repairs take precedence over new reads.
Existing hypothesis questions are preserved exactly: a narrower observation must use
a separate candidate or new hypothesis rather than replacing the original question.

`investigation_progress` records each evaluation round, resolved hypothesis IDs,
pending tasks, source coverage and repeated tool requests. Repeated searches do not
reset the no-source-progress check. `consumption_by_phase` records calls, accounted
and estimated tokens, reported input/output tokens, and prompt-character volume by
cognitive phase. Estimates are never relabelled as provider-reported usage.

The provider history may omit uncited search hits while retaining cited lines and
tool-call/response pairing. The authoritative graph history and provenance ledger
remain intact.

## Continue a partial run

Use the same request JSON and add `continuation` containing the entire previous
`BoundaryResult`, then pass it through the runner's existing `--request` option.
The repository, commit, snapshot hash and request fingerprint (including criteria
and caller architectural context) must match. Results created before the fingerprint
was introduced cannot be used as trusted continuation input.

Continuation reuses the plan and hypotheses. It re-delivers cited source through
the normal bounded tools and access checks, replaces old citations with fresh ones,
and re-evaluates conclusions before further investigation. Tool re-delivery is
charged to the new run; it is not a privileged import of serialized evidence.
Changed or unavailable source cannot inherit an accepted conclusion. Previous
consumption appears separately in `continuation_usage`, while ordinary model/tool
and token counters describe this run.

For a fair comparison, use the same repository commit, request, model and operating
limits. Compare resolved questions, grounded conclusions, relevant source coverage,
repeated requests and phase costs; more findings or more tokens alone is not progress.
