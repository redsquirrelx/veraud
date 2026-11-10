"""V2 bindings for the existing coordinator dispatch/collection infrastructure."""

import json
from copy import copy

from server.agent_services.budgeting.shared_tokens import SharedTokenBudget
from server.runtimes.coordination.execution import (
    CoordinatorExecution,
    CoordinatorSynthesisExecution,
)
from server.runtimes.coordination.synthesis import stable_id
from server.services.execution_failures import (
    ExecutionValidationError,
    failure_from_exception,
)

from .registry import registered_investigators
from .schemas import Assignment, InvocationRecord, RawInvocation
from .validation import validate_plan


def investigator_request(spec, assignment, request, repository):
    data = {"original_objective": request.original_objective or request.objective,
        "delegated_objective": request.objective, "targets": assignment.targets or None,
        "constraints": assignment.constraints, "repository_context": request.repository_context,
        "repository_id": repository.name, "commit": repository.commit, "snapshot_hash": repository.snapshot_hash,
        "scope_rule": "Respect the semantic scope in the objectives. Missing paths are unresolved localization, not an instruction to audit the whole repository."}
    fields = spec.request_class.model_fields
    kwargs = {}
    if "objective" in fields:
        kwargs["objective"] = assignment.objective
    for field in ("follow_up", "follow_up_diagnostics"):
        if field in fields:
            kwargs[field] = getattr(request, field)
    if "constraints" in fields:
        kwargs["constraints"] = assignment.constraints
    if "targets" in fields:
        kwargs["targets"] = assignment.targets
    if "documented_architecture" in fields:
        kwargs["documented_architecture"] = request.documented_architecture
    if assignment.investigator_id in request.continuations:
        if "continuation" not in fields:
            raise ExecutionValidationError("unsupported_continuation", "This investigator has no native result-continuation contract; no substitute run was fabricated.")
        kwargs["continuation"] = spec.result_class.model_validate(request.continuations[assignment.investigator_id])
    # Native validation rejects oversized context instead of truncating constraints.
    if "architectural_context" in fields:
        kwargs["architectural_context"] = json.dumps(data, ensure_ascii=False)
    return spec.request_class(**kwargs)


class InvestigationDispatch(CoordinatorExecution):
    synthesis_execution_type = CoordinatorSynthesisExecution  # Infrastructure only; never call its LLM nodes.
    raw_invocation_type = RawInvocation
    invocation_record_type = InvocationRecord

    def __init__(self, execution, state):
        self.registry = registered_investigators()
        owner = copy(execution.owner)
        owner.config = execution.config
        super().__init__(owner, execution.tools, execution.request)
        self.spent = state["consumption"]
        if self.token_budget is None:
            self.token_budget = SharedTokenBudget(execution.token_limit)
            if self.spent.accounted_tokens:
                reservation = self.token_budget.reserve(self.spent.accounted_tokens)
                if reservation is None:
                    self.token_budget = None  # Existing admission will reject the exhausted finite envelope.
                else:
                    reservation.settle(self.spent.accounted_tokens)
        count = max(1, len(state["plan"].assignments) if state.get("plan") else 0)
        resources = self.resources()
        limits = self.config.invocation_limits
        self.config = self.config.model_copy(update={"invocation_limits": limits.model_copy(update={
            "max_model_calls": max(4, min(limits.max_model_calls, max(0, resources["calls"]) // count)),
            "max_tool_calls": min(limits.max_tool_calls, max(0, resources["tools"]) // count),
            "max_total_tokens": max(1000, min(limits.max_total_tokens, max(0, resources["tokens"]) // count))})})

    def build_graph(self):
        return None  # The domain graph belongs to ReusabilityExecution, not this binding.

    def collect_received(self, raw, state):
        pass  # Deliberately defer collection to the collect_findings node.

    def investigator_request(self, spec, assignment, context):
        return spec.request_class.model_validate(assignment.request).model_copy(deep=True)

    def invocation_config(self, spec, limits):
        config = super().invocation_config(spec, limits)
        return config

    def invocation_evidence(self, value, child):
        references = [*self.references(child), *getattr(value, "evidence", [])]
        return list({ref.model_dump_json(): ref for ref in references}.values())

    def validate_collected_result(self, result, raw, state):
        try:
            super().validate_collected_result(result, raw, state)
        except ExecutionValidationError as error:
            if error.failure.code != "evidence_provenance_mismatch":
                raise
            # Runner retains findings with integrity limitations; do not discard
            # the whole batch for a provenance mismatch.
            object.__setattr__(result, "limitations", [*result.limitations,
                "Finding evidence provenance mismatch; retained with integrity limitation like the raw manager output."])
        if any(getattr(result, field) < 0 for field in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")):
            raise ExecutionValidationError("invalid_investigator_consumption", "Investigator reported negative consumption; original report is retained.")
        files = {file.id: file for file in self.tools.accessible_snapshot.files}
        ledger = {}
        inconsistent = []
        for ref in [*raw.evidence, *result.evidence]:
            source = files.get(ref.file_id)
            if (not source or not ref.id or not ref.tool_call_id or ref.path != source.path or ref.content_hash != source.content_hash
                or ref.snapshot_hash != state["snapshot_hash"] or ref.commit != result.commit
                or ref.kind == "source" and not (ref.start_line and ref.end_line and 1 <= ref.start_line <= ref.end_line <= (source.line_count or 0))):
                inconsistent.append(ref.id if ref.id else "<missing-id>")
                if ref.id and ref.id not in ledger:
                    ledger[ref.id] = ref
                continue
            if ref.id in ledger and ledger[ref.id] != ref:
                inconsistent.append(ref.id)
                continue
            ledger[ref.id] = ref
        if inconsistent:
            object.__setattr__(result, "limitations", [*result.limitations,
                f"Investigator evidence inconsistencies retained ({len(inconsistent)} refs); valid ledger entries preserved."])
        ids = [finding.id for finding in result.findings]
        if len(ids) != len(set(ids)):
            raise ExecutionValidationError("duplicate_finding_id", "Investigator returned conflicting local finding identifiers; raw output is retained.")
        for finding in result.findings:
            if (not finding.id or set(finding.evidence_ids) - ledger.keys()
                or any(ledger.get(ref.id) != ref for ref in finding.evidence)
                or not any(ref.kind == "source" for ref in finding.evidence)):
                # Retain the finding like the runner raw output; do not discard the whole batch.
                object.__setattr__(result, "missing_information", [*result.missing_information,
                    f"Finding {finding.id}: citations are not fully supported by the investigator ledger; retained like the raw manager output."])

    def result_status(self, result):
        # V2 completion describes execution/coverage, never a finding verdict.
        # Do not use the V1 collector's validation_status-based classification.
        if getattr(result, "status", None) == "failed" or result.plan is None and not result.evidence:
            return "failed"
        reasons = {reason for spec in self.registry.values() if isinstance(result, spec.result_class) for reason in spec.completed_reasons}
        if (result.termination_reason in reasons and result.plan and not result.missing_information
            and getattr(result, "status", "completed") == "completed" and not getattr(result, "tool_failures", [])
            and not any(h.status in {"pending", "inconclusive"} for h in result.hypotheses)
            and not getattr(result, "inconclusive_investigations", [])
            and not any(getattr(row, "status", None) == "inconclusive" for row in getattr(result, "investigation_results", []))
            and getattr(result, "evaluation_evidence_status", None) != "stale"
            and not getattr(result, "pending_evaluation_evidence_ids", [])
            and getattr(result, "next_phase", None) is None and any(ref.kind == "source" for ref in result.evidence)):
            return "completed"
        return "partial"

    def invocation_status(self, result):
        """Web lifecycle uses the same native completion policy as collection."""
        return self.result_status(result)


async def delegate_investigations(execution, state):
    dispatch = execution.dispatch = InvestigationDispatch(execution, state)
    initial, pending, rejected, seen, issued = [], [], {}, set(), set()
    plan = state.get("plan")
    for index, source in enumerate(plan.assignments if plan else []):
        assignment = Assignment(invocation_id=stable_id("reusability-invocation", [state["snapshot_hash"], index, source.model_dump(mode="json")]),
            investigator_id=source.investigator_id, round=1, question=source.objective, targets=source.targets,
            source=source, commitments=execution.request.follow_up, diagnostics=execution.request.follow_up_diagnostics)
        initial.append(assignment)
        try:
            if source.model_dump_json() in seen or source.investigator_id not in {item.id for item in state["investigator_catalog"]}:
                raise ExecutionValidationError("invalid_investigator_assignment", "Duplicate or excluded investigator assignment was not dispatched.")
            seen.add(source.model_dump_json())
            catalog = {key: spec.capability for key, spec in dispatch.registry.items()}
            validated = validate_plan(plan.model_copy(update={"assignments": [source]}), execution.request, catalog, dispatch.paths).assignments[0]
            spec = dispatch.registry[source.investigator_id]
            sent = investigator_request(spec, validated, execution.request, execution.tools.accessible_snapshot.repository)
            fingerprint = source.investigator_id, sent.model_dump_json()
            if fingerprint in issued:
                raise ExecutionValidationError("duplicate_invocation_request", "An identical native investigator request was already scheduled; no duplicate investigation was started.")
            issued.add(fingerprint)
            assignment = assignment.model_copy(update={"targets": validated.targets, "question": sent.objective,
                "request": sent.model_dump(mode="json"),
                "commitments": sent.follow_up if "follow_up" in spec.request_class.model_fields else [],
                "diagnostics": sent.follow_up_diagnostics if "follow_up_diagnostics" in spec.request_class.model_fields else []})
            initial[-1] = assignment
            pending.append(assignment)
        except (ValueError, KeyError) as error:
            rejected[assignment.invocation_id] = RawInvocation(assignment=assignment, status="skipped",
                failure=failure_from_exception(error, "prepare_investigator_request"))
    working = {**state, "pending_assignments": pending, "investigation_results": [], "execution_records": []}
    update = await dispatch.delegate_investigations(working)
    received = {row.assignment.invocation_id: row for row in update["execution_records"]}
    received.update(rejected)
    return {"initial_plan": initial, "execution_records": [received[a.invocation_id] for a in initial]}


def collect_findings(execution, state):
    dispatch = execution.dispatch
    if state.get("collected_count") == len(state.get("execution_records", [])) and "investigation_results" in state:
        return {}
    update = dispatch.collect_findings({**state, "investigation_results": [], "rounds_completed": 0})
    # Provider scopes are authoritative when a producer underreports token usage.
    for index, record in enumerate(update["investigation_results"]):
        scope = dispatch.invocation_tokens.get(record.assignment.invocation_id)
        if scope is not None and (scope.used > record.consumption.accounted_tokens or scope.estimated > record.consumption.estimated_tokens):
            usage = record.consumption.model_copy(update={"accounted_tokens": max(scope.used, record.consumption.accounted_tokens),
                "estimated_tokens": max(scope.estimated, record.consumption.estimated_tokens)})
            dispatch.spent = dispatch.spent.model_copy(update={field: getattr(dispatch.spent, field) + getattr(usage, field) - getattr(record.consumption, field)
                for field in ("accounted_tokens", "estimated_tokens")})
            updated = record.model_copy(update={"consumption": usage,
                "status": "partial" if record.status == "completed" else record.status,
                "warnings": [*record.warnings, "Reported tokens differed from the provider ledger; observed consumption was preserved."]})
            update["investigation_results"][index] = dispatch._collected_records[record.assignment.invocation_id] = updated
    return {**update, "consumption": dispatch.reported_consumption}
