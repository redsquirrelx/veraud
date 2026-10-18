"""Adapt the existing security scanners to snapshot-backed Blackboard audits."""

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, Field

from ...blackboard.models import Assessment, Evidence, Finding
from ...blackboard.publication import Publication
from ...runtimes.investigation.provider import ProviderPacer
from ...runtimes.repository.model_runtime import ModelGateway
from ...runtimes.repository.timing import within_deadline
from ..schemes.base import AuditRequest, Criterion
from .config import SecurityConfig
from .secret_scanner.agent import SECRET_PATTERNS
from .security_manager import SecuritySupervisorAgent


class SecurityAuditRequest(AuditRequest):
    objective: str = "Evaluar seguridad con los escáneres estáticos existentes y documentar sus limitaciones."
    targets: list[str] = Field(default_factory=list)
    quality_attribute: str = Field(default="security", pattern="^security$")


class SecurityAuditResult(BaseModel):
    status: str


def redact(value):
    """Keep credential values out of prompts, portable snapshots and reports."""
    import re

    for pattern in SECRET_PATTERNS:
        value = re.sub(pattern["regex"], "[CREDENCIAL REDACTADA]", value)
    return value


async def run_security_audit(tools, request, limits, model, board, identity):
    snapshot = tools.accessible_snapshot
    publication = Publication(board, "security", identity=identity)
    evidence_ids, finding_ids, incidents, scanned = [], [], [], []
    incomplete_reasons = []

    def record_incident(reason, description):
        if reason not in incomplete_reasons:
            incomplete_reasons.append(reason)
        incidents.append(description)
    calls = 0
    policy = SecurityConfig()
    supervisor = SecuritySupervisorAgent(config=policy)
    # This adapter uses only the selected, managed provider. Never consult an
    # ambient OPENAI_API_KEY through the legacy synchronous remediation path.
    supervisor.remediation_agent.api_key = None
    reservations = []
    pacer = ProviderPacer(rate_limits=limits.provider_rate_limits, provider_config=limits)

    async def generate(prompt):
        with tools.timing.quota_wait() as waiting:
            quota = await within_deadline(pacer.acquire(max(1, len(prompt)) + limits.max_output_tokens,
                on_wait=lambda seconds, reasons: waiting.update(reason="+".join(reasons),
                    until=tools.timing.clock() + seconds, source="local_rolling_window")), tools.timing)
        response = await model.ainvoke(prompt)
        usage = getattr(response, "usage_metadata", None)
        if isinstance(usage, dict) and usage.get("input_tokens") is not None and usage.get("output_tokens") is not None:
            actual = usage["input_tokens"] + usage["output_tokens"]
            reservations[-1].settle(actual)
            pacer.settle(quota, actual)
        return response

    gateway = ModelGateway(SimpleNamespace(generate=generate), provider_config=limits,
        remaining_seconds=lambda: tools.timing.active_remaining)

    def guard(prompt, attempt):
        nonlocal calls
        reserve = max(1, len(prompt)) + limits.max_output_tokens
        if calls >= limits.max_model_calls:
            raise ValueError("security_remediation_call_budget_exhausted")
        if tools.token_budget.used + reserve > limits.max_total_tokens:
            raise ValueError("security_remediation_local_budget_exhausted")
        reservation = tools.token_budget.reserve(reserve)
        if reservation is None:
            raise ValueError("security_remediation_budget_exhausted")
        reservations.append(reservation)
        calls += 1

    gateway.request_guard = guard

    def publish_assessment(status, reason):
        record = Assessment(**publication._identity("assessment", "security"), repository_id=snapshot.repository.name,
            commit=snapshot.repository.commit, snapshot_hash=snapshot.repository.snapshot_hash, objective=request.objective,
            targets=tuple(request.targets), quality_attribute="security", status=status, termination_reason=reason,
            summary=f"Seguridad: {len(scanned)} archivos inspeccionados; {len(finding_ids)} candidatos conservados.",
            finding_ids=tuple(finding_ids), evidence_ids=tuple(evidence_ids),
            limitations=("Detecciones heurísticas del módulo existente; no confirman explotabilidad.",
                "SCA conserva su búsqueda por nombre, sin resolver versiones afectadas.",
                "DAST no ejecutado; los parches propuestos no acreditan una corrección validada.", *incidents),
            coverage={"scanned_files": scanned, "planned_files": [f.path for f in candidates],
                "completed_files": [path for path, coverage in file_coverage.items() if coverage["complete"]],
                "files": file_coverage, "dast": "not_evaluated"},
            consumption={"model_calls": calls, "tool_calls": tools.budget_usage.tool_calls,
                "accounted_tokens": tools.token_budget.used, "estimated_tokens": tools.token_budget.estimated,
                "model_calls_estimated": False},
            details={"quality_attribute": "security", "subcharacteristic": "static_security",
                "security_analysis": {"scanned_files": scanned, "incidents": incidents, "provider_calls": gateway.calls,
                    "effective_config": limits.model_dump(mode="json"),
                    "audit_token_limit": tools.token_budget.root.limit,
                    "incomplete_reasons": list(incomplete_reasons),
                    "remediation": "proposal_only", "dast": "not_evaluated"}})
        # A synchronous terminal receipt records consumed resources even after
        # the host revokes further work. Provider tasks cannot publish records.
        board.publish_assessment(record)

    candidates = sorted([f for f in snapshot.files if not request.targets or any(
        f.path == target or f.path.startswith(target.rstrip("/") + "/") for target in request.targets)], key=lambda f: f.path)
    file_coverage = {source.path: {"file_id": source.id, "total_lines": source.line_count,
        "read_ranges": [], "pending_ranges": [{"start_line": 1, "end_line": source.line_count}], "complete": False}
        for source in candidates}

    async def stage_source(source, temporary):
        """Reassemble consecutive tool excerpts; publish each range before continuing."""
        coverage = file_coverage[source.path]
        parts, source_refs = [], []
        start, total = 1, source.line_count or 1
        requested_end = min(total, limits.max_source_lines)
        while start <= total:
            await asyncio.sleep(0)
            if tools.budget_usage.tool_calls >= limits.max_tool_calls:
                record_incident("tool_call_limit", f"Presupuesto de lecturas agotado al inspeccionar {source.path}.")
                break
            response = tools.execute("get_source_excerpt", {"path": source.path, "start_line": start,
                "end_line": requested_end}, tool_call_id=f"security-read-{tools.budget_usage.tool_calls + 1}")
            if response.error or not response.evidence:
                code = getattr(response.error, "code", None)
                if code in {"response_limit_exceeded", "content_budget_exhausted"} and requested_end > start:
                    requested_end = start + (requested_end - start) // 2
                    continue
                record_incident("security_source_read_failed", f"No se pudo leer {source.path} desde la línea {start}.")
                break
            ref = response.evidence[0]
            if ref.start_line != start or ref.end_line is None or not start <= ref.end_line <= total:
                record_incident("security_source_read_failed", f"Rango de lectura no consecutivo para {source.path}:{start}.")
                break
            parts.append(response.data["content"])
            local_id = f"{source.id}/{start}-{ref.end_line}"
            evidence_id = publication.record_id("evidence", local_id)
            board.publish_evidence(Evidence(**publication._identity("evidence", local_id), kind="source",
                source=source.path, content=redact(parts[-1]), snapshot_hash=ref.snapshot_hash, commit=snapshot.repository.commit,
                file_id=ref.file_id, content_hash=ref.content_hash, start_line=ref.start_line, end_line=ref.end_line,
                tool_call_id=ref.tool_call_id, symbol_ids=tuple(s.id for s in snapshot.symbols if s.file_id == source.id
                    and s.start_line <= ref.end_line and (s.end_line or s.start_line) >= ref.start_line),
                details={"quality_attribute": "security", "redacted": True}))
            evidence_ids.append(evidence_id)
            source_refs.append((evidence_id, start, ref.end_line))
            coverage["read_ranges"].append({"start_line": start, "end_line": ref.end_line, "evidence_id": evidence_id})
            start = ref.end_line + 1
            coverage["pending_ranges"] = [{"start_line": start, "end_line": total}] if start <= total else []
            coverage["complete"] = start > total
            requested_end = min(total, start + limits.max_source_lines - 1)
        if not parts:
            return None, []
        if not coverage["complete"]:
            record_incident("security_source_truncated", f"Lectura parcial de {source.path}: líneas pendientes {start}–{total}.")
        staged = Path(temporary) / source.path
        staged.parent.mkdir(parents=True, exist_ok=True)
        # Excerpts omit separators at range boundaries. Restore those separators
        # (including blank lines) so legacy scanners retain original line numbers.
        staged.write_text("\n".join(parts) + "\n", encoding="utf-8")
        scanned.append(source.path)
        return staged, source_refs

    if not candidates:
        record_incident("security_empty_scope", "No hay archivos accesibles para inspeccionar en el alcance seleccionado.")
    if len(candidates) > limits.max_scan_files:
        record_incident("security_file_limit", "El alcance supera el límite de archivos de seguridad.")
    try:
        # Legacy scanners read an isolated reconstruction of controlled excerpts.
        # The checkout is never modified; pending ranges remain explicit.
        with tempfile.TemporaryDirectory(prefix="veraud-security-") as temporary:
            for source in candidates[:limits.max_scan_files]:
                await asyncio.sleep(0)
                if tools.budget_usage.tool_calls >= limits.max_tool_calls:
                    record_incident("tool_call_limit", "Presupuesto de lecturas agotado.")
                    break
                staged, source_refs = await stage_source(source, temporary)
                if staged is None:
                    continue
                findings = [*supervisor.sast_agent.scan_path(str(staged)), *supervisor.secret_agent.scan_path(str(staged)),
                    *supervisor.sca_agent.scan_dependencies(str(staged.parent))] if staged.name in {"package.json", "requirements.txt"} else [
                    *supervisor.sast_agent.scan_path(str(staged)), *supervisor.secret_agent.scan_path(str(staged))]
                # SCA scans its directory; retain only this manifest's results.
                findings = [f for f in findings if Path(f.file_path) == staged]
                supervisor.enrichment_agent.enrich(findings)
                for number, original in enumerate(findings):
                    original.file_path = source.path
                    original.snippet = redact(original.snippet)
                    original.matched_text = redact(original.matched_text)
                    fallback = supervisor.remediation_agent._fallback_patch(original)
                    interrupted = None
                    try:
                        prompt = policy.remediation_system_prompt + "\n" + json.dumps(original.to_dict(), ensure_ascii=False)
                        if len(prompt) > limits.max_context_characters:
                            raise ValueError("security_remediation_context_limit")
                        with tools.timing.stage("security_remediation"):
                            proposed = json.loads(await gateway(prompt))
                        if not isinstance(proposed, dict) or not isinstance(proposed.get("patch_code"), str):
                            raise TypeError("invalid_security_remediation")
                        original.remediation = {"llm_generated": True, "validated_by_sast": False,
                            "patch_code": redact(proposed["patch_code"]), "explanation": redact(str(proposed.get("explanation", "")))}
                    except asyncio.CancelledError as error:
                        interrupted = error
                        original.remediation = {**fallback, "llm_generated": False, "validated_by_sast": False,
                            "interrupted": True}
                    except Exception as error:  # noqa: BLE001 - retain original candidates on bounded provider failure
                        reason = {
                            "security_remediation_call_budget_exhausted": "model_call_limit",
                            "security_remediation_budget_exhausted": "audit_token_limit",
                            "security_remediation_local_budget_exhausted": "token_limit",
                            "security_remediation_context_limit": "context_limit",
                        }.get(str(error), "security_remediation_fallback")
                        record_incident(reason, f"Remediación local para {source.path}: {type(error).__name__}.")
                        original.remediation = {**fallback, "llm_generated": False, "validated_by_sast": False}
                    supervisor.validator_agent.validate_patches([original])
                    kept = bool(supervisor.verifier_agent.filter_false_positives([original]))
                    local_id = f"{source.id}/{original.rule_id}/{original.line_number}/{number}"
                    criterion = Criterion(id=original.rule_id, description=original.rule_name, origin="explicit",
                        provenance="Regla del escáner de seguridad existente; clasificación " + original.owasp_category)
                    record = Finding(**publication._identity("finding", local_id), title=original.rule_name,
                        description=f"Candidato detectado por {original.rule_id} en {source.path}:{original.line_number}.",
                        kind="design_observation", criterion_id=criterion.id, criterion=criterion,
                        components=(source.id,), justification="Coincidencia heurística; pendiente de validación contextual.",
                        modularity_impact="Posible impacto de seguridad; no se ha demostrado explotabilidad.",
                        severity=original.severity.lower(), evidence_ids=tuple(identifier for identifier, first, last in source_refs
                            if staged.name in {"package.json", "requirements.txt"} or first <= original.line_number <= last),
                        recommendation=redact(str(original.remediation.get("explanation", "Revisar el candidato en su contexto."))),
                        details={"quality_attribute": "security", "subcharacteristic": "static_security",
                            "validation_status": "insufficient_evidence", "review_rationale": "El filtro legacy no constituye verificación técnica.",
                            "legacy_filter_kept": kept, "security_finding": original.to_dict()})
                    board.publish_finding(record)
                    finding_ids.append(record.id)
                    if interrupted is not None:
                        raise interrupted
        if len(scanned) < len(candidates):
            record_incident("security_scope_incomplete", "Quedan archivos sin inspeccionar en el alcance seleccionado.")
        status = "partial" if incomplete_reasons else "completed"
        publish_assessment(status, incomplete_reasons[0] if incomplete_reasons else "security_scope_completed")
        return SecurityAuditResult(status=status)
    except BaseException:
        record_incident("security_interrupted", "El análisis de seguridad se interrumpió antes de completar las etapas previstas.")
        publish_assessment("partial", "security_interrupted")
        raise
