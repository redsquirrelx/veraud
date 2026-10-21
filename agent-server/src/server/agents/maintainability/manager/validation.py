"""Manager-specific scope, accounting, nested provenance and coverage checks."""

from ....config.token_budget import token_budget_exceeded
from ....runtimes.coordination.synthesis import evidence_key
from ....runtimes.investigation.schemas import EvidenceReference
from ....services.execution_failures import ExecutionValidationError


def validate_call_capacity(limits, request):
    """Require room for the initial selected wave plus its closing synthesis."""
    from ..modularity.coordinator.registry import INVESTIGATORS as MODULARITY
    from ..reusability.coordinator.registry import INVESTIGATORS as REUSABILITY
    from .registry import COORDINATORS

    selected = [key for key in request.dimensions if key in COORDINATORS]
    coordinator = limits.invocation_limits
    required = len(selected) * coordinator.max_model_calls + 1 + limits.max_schema_retries
    if selected and limits.max_model_calls < required:
        raise ValueError(f"manager_call_budget_too_small: available={limits.max_model_calls}, required={required} "
            f"({len(selected)} coordinators plus synthesis). Configure call_limits.manager.max_model_calls.")
    required_tools = len(selected) * coordinator.max_tool_calls
    if selected and limits.max_tool_calls < required_tools:
        raise ValueError(f"manager_tool_budget_too_small: available={limits.max_tool_calls}, required={required_tools} "
            f"({len(selected)} coordinators). Configure call_limits.manager.max_tool_calls.")
    for key in selected:
        registry = MODULARITY if key == "modularity" else REUSABILITY
        required = len(registry) * coordinator.invocation_limits.max_model_calls + 1 + coordinator.max_schema_retries
        if coordinator.max_model_calls < required:
            raise ValueError(f"coordinator_call_budget_too_small: coordinator={key}, available={coordinator.max_model_calls}, "
                f"required={required} ({len(registry)} investigators plus synthesis). Configure call_limits.coordinator.max_model_calls.")
        required_tools = len(registry) * coordinator.invocation_limits.max_tool_calls
        if coordinator.max_tool_calls < required_tools:
            raise ValueError(f"coordinator_tool_budget_too_small: coordinator={key}, available={coordinator.max_tool_calls}, "
                f"required={required_tools} ({len(registry)} investigators). Configure call_limits.coordinator.max_tool_calls.")


def valid_reference(ref, tools):
    source = next((f for f in tools.accessible_snapshot.files if f.id == ref.file_id), None)
    return bool(source and ref.path == source.path and ref.content_hash == source.content_hash
        and ref.snapshot_hash == tools.context.input.snapshot_hash
        and ref.commit in {None, tools.accessible_snapshot.repository.commit}
        and (ref.kind != "source" or ref.start_line is not None and ref.end_line is not None
             and 1 <= ref.start_line <= ref.end_line <= (source.line_count or 0)))


def _validate_nested_evidence(value, invocation_id, known, check_reference, location="result"):
    """Every evidence record embedded in domain analyses must match the collected ledger."""
    if isinstance(value, dict):
        if {"id", "path", "file_id", "content_hash", "snapshot_hash", "tool_call_id", "kind"} <= value.keys():
            ref = EvidenceReference.model_validate(value)
            if not check_reference(ref) or known.get((invocation_id, ref.id)) != ref:
                collected = known.get((invocation_id, ref.id))
                fields = sorted(key for key in EvidenceReference.model_fields
                    if collected is None or getattr(collected, key) != getattr(ref, key))
                raise ExecutionValidationError("uncollected_nested_evidence", "La evidencia anidada no coincide con el registro recopilado.",
                    diagnostics=[f"location={location}", f"reference={invocation_id}/{ref.id}",
                        "differing_fields=" + ",".join(fields)])
            return
        for key, item in value.items():
            # Domain field names come from the validated schema; no source values.
            _validate_nested_evidence(item, invocation_id, known, check_reference, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_nested_evidence(item, invocation_id, known, check_reference, f"{location}[{index}]")


def validate_assessment(result, assignment, *, snapshot, request, check_reference, verify_references, baseline=None):
    """Reject mismatched or unsupported coordinator output before it contributes knowledge."""
    if (result.repository_id != snapshot.name or result.commit != snapshot.commit or result.snapshot_hash != snapshot.snapshot_hash
            or result.objective != assignment.question or result.targets != assignment.targets):
        raise ExecutionValidationError("coordinator_provenance_mismatch", "El alcance o procedencia del coordinador no coincide con su asignación.")
    if assignment.investigator_id == "reusability" and result.target_context != request.target_context:
        raise ExecutionValidationError("target_context_mismatch", "El contexto objetivo del resultado no coincide con la solicitud.")
    validate_accounting(result, assignment.budget, baseline=baseline)
    _validate_invocations(result, snapshot, check_reference, verify_references)
    _validate_consolidated_findings(result, check_reference)


def validate_accounting(result, budget, *, baseline=None):
    usage = result.consumption
    if baseline is not None:
        if (result.baseline_assessment_id != baseline.assessment_id or result.initial_plan != baseline.initial_plan
                or result.targets != baseline.targets or not set(baseline.resolved_gap_ids) <= set(result.resolved_gap_ids)):
            raise ExecutionValidationError("invalid_continuation_baseline", "La continuación no conserva la evaluación base y su alcance.")
        records = {r.assignment.invocation_id: r for r in result.invocations}
        if any(r.assignment.invocation_id not in records or records[r.assignment.invocation_id] != r for r in baseline.invocations):
            raise ExecutionValidationError("modified_baseline_receipt", "La continuación modificó u omitió una investigación histórica.")
        usage = usage.model_copy(update={key: getattr(usage, key) - getattr(baseline.consumption, key)
            for key in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")})
        old_ids = {r.assignment.invocation_id for r in baseline.invocations}
        if any(sum(getattr(r.consumption, key) for r in result.invocations if r.assignment.invocation_id not in old_ids)
                > getattr(usage, key) for key in ("model_calls", "tool_calls", "accounted_tokens")):
            raise ExecutionValidationError("underreported_continuation_usage", "La continuación no contabiliza sus nuevas investigaciones.")
    elif result.baseline_assessment_id is not None:
        raise ExecutionValidationError("unknown_continuation_baseline", "La evaluación declara una base que no fue asignada por el manager.")
    if budget is None or any(getattr(usage, k) < 0 for k in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")):
        raise ExecutionValidationError("invalid_accounting", "El consumo declarado o la reserva de recursos no es válido.")
    if (usage.model_calls > budget.max_model_calls or usage.tool_calls > budget.max_tool_calls
            or token_budget_exceeded(usage.accounted_tokens, budget.max_total_tokens) or usage.estimated_tokens > usage.accounted_tokens):
        raise ExecutionValidationError("usage_exceeded_envelope", "El consumo declarado supera el presupuesto reservado.")
    if len({r.assignment.invocation_id for r in result.invocations}) != len(result.invocations):
        raise ExecutionValidationError("duplicate_invocations", "El resultado contiene identificadores de invocación duplicados.")
    if any(sum(getattr(r.consumption, k) for r in result.invocations) > getattr(result.consumption, k)
           for k in ("model_calls", "tool_calls", "accounted_tokens")):
        raise ExecutionValidationError("underreported_nested_usage", "El consumo del coordinador es menor que el de sus investigaciones.")
    return usage


def _validate_invocations(result, snapshot, check_reference, verify_references):
    known = {}
    for record in result.invocations:
        if any(getattr(record.consumption, k) < 0 for k in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")):
            raise ExecutionValidationError("invalid_nested_accounting", "Una investigación anidada declara un consumo inválido.")
        for ref in record.evidence:
            if not check_reference(ref):
                raise ExecutionValidationError("invalid_nested_evidence", "Una referencia anidada no corresponde al snapshot auditado.")
            if (record.assignment.invocation_id, ref.id) in known:
                raise ExecutionValidationError("duplicate_nested_evidence", "El registro contiene identificadores de evidencia duplicados.")
            known[(record.assignment.invocation_id, ref.id)] = ref
        if record.result:
            child = record.result
            if (child.snapshot_hash != snapshot.snapshot_hash or child.commit != snapshot.commit
                    or child.repository_id != snapshot.name or child.objective != record.assignment.question):
                raise ExecutionValidationError("invalid_nested_provenance", "La procedencia de una investigación anidada no coincide con su asignación.")
            for finding in child.findings:
                for ref in finding.evidence:
                    if known.get((record.assignment.invocation_id, ref.id)) != ref:
                        raise ExecutionValidationError("uncollected_finding_evidence", "Un hallazgo cita evidencia que no consta en el registro recopilado.")
                if finding.validation_status == "accepted":
                    _, mismatch = verify_references(finding.evidence)
                    if mismatch or not any(e.kind == "source" for e in finding.evidence):
                        raise ExecutionValidationError("unverifiable_source_attribution", "No se pudo verificar la fuente de un hallazgo aceptado.")
            _validate_nested_evidence(child.model_dump(), record.assignment.invocation_id, known, check_reference)


def _validate_consolidated_findings(result, check_reference):
    for group in result.consolidated_findings:
        for contribution in group.contributions:
            record = next((r for r in result.invocations if r.assignment.invocation_id == contribution.invocation_id), None)
            if (not record or not record.result or contribution.investigator_id != record.assignment.investigator_id
                    or contribution.reference != f"{contribution.invocation_id}/{contribution.finding.id}"
                    or not any(f == contribution.finding and f.validation_status == "accepted" for f in record.result.findings)):
                raise ExecutionValidationError("unsupported_contribution", "Una contribución consolidada no corresponde a un hallazgo aceptado de su investigación.")
        available = {evidence_key(e) for c in group.contributions for e in c.finding.evidence}
        if any(evidence_key(e) not in available or not check_reference(e) for e in group.evidence):
            raise ExecutionValidationError("unsupported_consolidated_evidence", "La evidencia consolidada no está respaldada por sus contribuciones.")


def coverage_issues(result, registry):
    """Require all registered lenses to finish a planned, source-backed investigation."""
    issues = []
    if result.status != "completed" or result.material_gaps:
        issues.append("Coordinator incomplete or material gaps unresolved.")
    if {a.investigator_id for a in result.initial_plan} != set(registry):
        issues.append("Coordinator initial plan does not cover its registered investigator lenses.")
    for investigator in registry:
        if not any(r.assignment.investigator_id == investigator and r.status == "completed" and r.result and r.result.plan
                   and getattr(r.result, "status", "completed") == "completed" and not r.result.missing_information
                   and not any(h.status in {"pending", "inconclusive"} for h in r.result.hypotheses)
                   and any(e.kind == "source" for e in r.evidence) for r in result.invocations):
            issues.append(f"No completed planned source-backed investigation from {investigator}.")
    if any(g.status == "disputed" for g in result.consolidated_findings):
        issues.append("Disputed subordinate finding remains.")
    return issues
