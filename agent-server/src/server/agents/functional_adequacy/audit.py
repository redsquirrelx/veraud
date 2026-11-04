"""Repository-backed functional audit using the existing agent and report contracts."""

import hashlib
from types import SimpleNamespace

from config.agents.model import AgentSettings

from ...blackboard.models import Assessment, Evidence, Finding
from ...blackboard.publication import Publication
from ...runtimes.coordination.schemas import Consumption
from ...runtimes.invocation_reporting import report_invocation_phase
from ...runtimes.repository.budgeted_model import BudgetedModel
from .agent import FunctionalAdequacyAgent
from .repository_adapter import MAX_FRAGMENTS, prepare_snapshot_input


async def run_functional_audit(snapshot, requirements, limits, model, board, identity, tokens, timing):
    await report_invocation_phase("prepare")
    prepared = prepare_snapshot_input(snapshot, requirements)
    fragments = prepared.code_fragments
    managed = BudgetedModel(model, limits, tokens, timing) if requirements else None
    agent = FunctionalAdequacyAgent(AgentSettings(agent_id="functional_adequacy", timeout_seconds=limits.timeout_seconds),
        SimpleNamespace(generate=managed.call, settings=SimpleNamespace(
            provider=getattr(model, "_llm_type", "managed"), name=getattr(model, "model_name", "functional_adequacy")))
        if managed is not None else None, config=limits)
    output = await agent.run(prepared)
    if output.audit_mode == "exploratory":
        return _publish_exploratory(snapshot, prepared, output, board, identity, tokens)
    publication = Publication(board, "functional_adequacy", identity=identity)
    fragment_index = {fragment.fragment_id: fragment for fragment in fragments}
    files = {source.path: source for source in snapshot.files}
    evidence_by_fragment = {}
    findings = []
    limitations = ["Evaluación semántica de los requisitos suministrados; no ejecuta pruebas funcionales ni confirma por sí sola cumplimiento o incumplimiento.",
        *output.limitations]
    if len(fragments) >= MAX_FRAGMENTS:
        limitations.append("La selección alcanzó el límite de fragmentos; puede existir código relevante fuera del alcance.")
    for result in output.results:
        evidence_ids = []
        for reference in result.evidence:
            fragment = fragment_index.get(reference.fragment_id)
            if fragment is None:
                continue
            if fragment.fragment_id not in evidence_by_fragment:
                path, lines = fragment.file_path.rsplit(":", 1)
                start, end = (int(value) for value in lines.split("-"))
                source = files[path]
                evidence = Evidence(id=publication.record_id("evidence", fragment.fragment_id),
                    agent_id="functional_adequacy", run_id=identity.run_id, invocation_id=identity.invocation_id,
                    kind="source", source=path, content=fragment.code, snapshot_hash=snapshot.repository.snapshot_hash,
                    commit=snapshot.repository.commit, file_id=source.id,
                    content_hash=hashlib.sha256(fragment.code.encode()).hexdigest(), tool_call_id="functional-retrieval",
                    start_line=start, end_line=end, details={"fragment_id": fragment.fragment_id})
                board.publish_evidence(evidence)
                evidence_by_fragment[fragment.fragment_id] = evidence.id
            evidence_ids.append(evidence_by_fragment[fragment.fragment_id])
        finding = Finding(id=publication.record_id("finding", result.requirement_id), agent_id="functional_adequacy",
            run_id=identity.run_id, invocation_id=identity.invocation_id, local_id=result.requirement_id,
            title=f"{result.requirement_id}: {result.status}", description=result.description,
            kind="design_observation", criterion_id=result.requirement_id,
            criterion={"id": result.requirement_id, "description": result.description,
                "origin": "explicit", "provenance": "Requisito funcional suministrado por el usuario."},
            components=tuple(dict.fromkeys(reference.file_path for reference in result.evidence)) or ("repository",),
            justification=result.justification, modularity_impact="Evaluación de adecuación funcional, no de modularidad.",
            evidence_ids=tuple(evidence_ids), details={"quality_attribute": "functional_adequacy",
                "subcharacteristic": "functional_correctness", "functional_requirement": result.model_dump(mode="json"),
                "validation_status": "insufficient_evidence", "limitations": limitations})
        board.publish_finding(finding)
        findings.append(finding.id)
    incomplete = any(item.status == "evidencia_insuficiente" for item in output.results) or len(fragments) >= MAX_FRAGMENTS
    status = "partial" if incomplete else "completed"
    board.publish_assessment(Assessment(agent_id="functional_adequacy", run_id=identity.run_id,
        invocation_id=identity.invocation_id, repository_id=snapshot.repository.name,
        snapshot_hash=snapshot.repository.snapshot_hash, commit=snapshot.repository.commit,
        objective="Contrastar los requisitos funcionales suministrados con el código de la revisión seleccionada.",
        quality_attribute="functional_adequacy", status=status,
        termination_reason="incomplete_evidence" if incomplete else "requirements_evaluated",
        summary=f"{output.fulfilled_requirements}/{output.total_requirements} requisitos clasificados como cumple ({output.score}%). "
            "El porcentaje se limita a los requisitos suministrados y no representa la calidad global del proyecto.",
        finding_ids=tuple(findings), evidence_ids=tuple(evidence_by_fragment.values()), limitations=tuple(limitations),
        consumption=Consumption(model_calls=managed.attempts, accounted_tokens=tokens.used, estimated_tokens=tokens.estimated),
        details={"quality_attribute": "functional_adequacy", "functional_output": output.model_dump(mode="json")}))
    return SimpleNamespace(status=status)


def _publish_exploratory(snapshot, prepared, output, board, identity, tokens):
    """Translate agent-owned output to main's existing evidence/report contracts."""
    publication = Publication(board, "functional_adequacy", identity=identity)
    files = {source.path: source for source in snapshot.files}
    evidence_index = {}
    findings = []
    limitations = list(output.limitations)
    truncated = len(prepared.code_fragments) >= MAX_FRAGMENTS
    if truncated:
        limitations.append("La selección alcanzó el límite de fragmentos; puede existir código relevante fuera del alcance.")
    subcharacteristics = {"completitud": "functional_completeness", "correccion": "functional_correctness",
        "pertinencia": "functional_appropriateness"}
    for result in output.findings:
        evidence_ids = []
        for reference in result.evidence:
            source = files.get(reference.file_path)
            if source is None or not reference.snippet:
                continue
            key = (reference.file_path, reference.start_line, reference.end_line, reference.symbol)
            if key not in evidence_index:
                evidence = Evidence(id=publication.record_id("evidence", repr(key)),
                    agent_id="functional_adequacy", run_id=identity.run_id, invocation_id=identity.invocation_id,
                    kind="source", source=reference.file_path, content=reference.snippet,
                    snapshot_hash=snapshot.repository.snapshot_hash, commit=snapshot.repository.commit, file_id=source.id,
                    content_hash=hashlib.sha256(reference.snippet.encode()).hexdigest(), tool_call_id="functional-exploration",
                    start_line=reference.start_line,
                    end_line=(reference.start_line + len(reference.snippet.splitlines()) - 1)
                    if reference.start_line is not None else None,
                    details={"fragment_id": reference.fragment_id, "symbol": reference.symbol})
                board.publish_evidence(evidence)
                evidence_index[key] = evidence.id
            evidence_ids.append(evidence_index[key])
        finding = Finding(id=publication.record_id("finding", result.finding_id), agent_id="functional_adequacy",
            run_id=identity.run_id, invocation_id=identity.invocation_id, local_id=result.finding_id,
            title=f"{result.capability_name}: {result.attribute} ({result.classification})",
            description=result.justification, kind="design_observation", criterion_id=result.attribute,
            criterion={"id": result.attribute, "description": result.criteria, "origin": "inferred",
                "provenance": "Indicador estático exploratorio; no es un requisito suministrado."},
            components=tuple(dict.fromkeys(reference.file_path for reference in result.evidence)) or ("repository",),
            justification=result.justification, modularity_impact="Evaluación de adecuación funcional, no de modularidad.",
            evidence_ids=tuple(evidence_ids), details={"quality_attribute": "functional_adequacy",
                "subcharacteristic": subcharacteristics[result.attribute], "functional_finding": result.model_dump(mode="json"),
                "audit_mode": "exploratory", "validation_status": "insufficient_evidence", "limitations": limitations})
        board.publish_finding(finding)
        findings.append(finding.id)
    incomplete = (not output.capabilities or not evidence_index or truncated or bool(prepared.repository_context.analysis_issues)
        or any(item.classification == "no_verificado" for item in output.findings))
    status = "partial" if incomplete else "completed"
    board.publish_assessment(Assessment(agent_id="functional_adequacy", run_id=identity.run_id,
        invocation_id=identity.invocation_id, repository_id=snapshot.repository.name,
        snapshot_hash=snapshot.repository.snapshot_hash, commit=snapshot.repository.commit,
        objective="Explorar las capacidades funcionales de la revisión seleccionada sin requisitos explícitos.",
        quality_attribute="functional_adequacy", status=status,
        termination_reason="incomplete_evidence" if incomplete else "capabilities_evaluated",
        summary=f"Auditoría exploratoria: {len(output.capabilities)} capacidades y {len(output.findings)} hallazgos estáticos. "
            "Sin requisitos no se calcula un porcentaje de cumplimiento ni de cobertura.",
        finding_ids=tuple(findings), evidence_ids=tuple(evidence_index.values()), limitations=tuple(limitations),
        consumption=Consumption(model_calls=0, accounted_tokens=tokens.used, estimated_tokens=tokens.estimated),
        details={"quality_attribute": "functional_adequacy", "functional_output": output.model_dump(mode="json")}))
    return SimpleNamespace(status=status)
