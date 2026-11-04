"""Report-specific graph nodes and deterministic, source-linked document assembly."""

import hashlib
import json
from collections import Counter
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel

from server.blackboard.interface import Blackboard
from server.reporting.input_validation import validate_extensions
from server.reporting.interpretation import (
    GENERATOR_VERSION,
    coverage_projection,
    decision,
    effective_view,
)
from server.reporting.knowledge import (
    AGENT_CATEGORIES,
    ATTRIBUTE_TITLES,
    SECURITY_SUBCHARACTERISTICS,
    SUBCHARACTERISTICS,
    category,
    reference,
    report_findings,
    statement,
)
from server.reporting.references import ReferenceCatalog
from server.reporting.schemas import (
    AttributeResult,
    AuditAnnexes,
    AuditConclusions,
    AuditMethodology,
    AuditScope,
    ConsolidatedRiskAnalysis,
    ExecutionTrace,
    ExecutiveSummary,
    FindingRelationship,
    FindingStatistics,
    ImprovementRecommendation,
    QualityResults,
    RecordReference,
    ReportEvidence,
    ReportGeneration,
    ReportIdentification,
    ReportRisk,
    ReportStatement,
    RepositoryRevision,
    SoftwareAuditReport,
    SoftwareDescription,
    SubcharacteristicResult,
)
from server.services.audit_diagnostics import execution_diagnostics, execution_records

SEVERITIES = ("critical", "high", "medium", "low", "info")
PRIORITIES = {"critical": "urgent", "high": "high", "medium": "medium", "low": "low", "info": "low"}


def unique(values):
    return list(dict.fromkeys(values))


def statistics(findings):
    return FindingStatistics(total=len(findings),
        by_severity=dict(Counter(item.severity or "undetermined" for item in findings)),
        by_verification={status: sum(item.verification_status == status for item in findings)
            for status in ("verified", "inconclusive", "discarded")},
        by_severity_and_verification={severity: dict(Counter(item.verification_status for item in findings
            if (item.severity or "undetermined") == severity)) for severity in (*SEVERITIES, "undetermined")},
        by_attribute=dict(Counter(item.quality_attribute for item in findings)),
        verified_by_component=dict(Counter(component for item in findings if item.verification_status == "verified" and item.lifecycle == "current"
            for component in set(item.components))), active_total=sum(item.lifecycle == "current" for item in findings),
        active_by_verification={status: sum(item.lifecycle == "current" and item.verification_status == status for item in findings)
            for status in ("verified", "inconclusive", "discarded")})


def evaluated_status(assessments, findings):
    if not assessments:
        return "partial" if findings else "not_evaluated"
    if all(item.status == "failed" for item in assessments) and not findings:
        return "failed"
    if any(item.status in {"partial", "failed"} or item.gaps for item in assessments):
        return "partial"
    if any(item.verification_status == "inconclusive" for item in findings):
        return "partial"
    return "completed"


def conclusion(title, status, findings):
    if status == "not_evaluated":
        return f"{title}: No evaluado. No se emite una valoración de calidad."
    verified = sum(item.verification_status == "verified" for item in findings)
    inconclusive = sum(item.verification_status == "inconclusive" for item in findings)
    return (f"{title}: evaluación { {'completed': 'completada', 'partial': 'parcial', 'failed': 'fallida'}[status]}. "
        f"Se registran {verified} hallazgos verificados y {inconclusive} inconclusos. "
        "La valoración se limita al alcance y las evidencias registrados; la ausencia de hallazgos no demuestra conformidad.")


class ReportExecution:
    def __init__(self, blackboard: Blackboard, run_id: str, issued_at: datetime):
        self.blackboard, self.run_id, self.issued_at = blackboard, run_id, issued_at

    def read_blackboard(self, state):
        # Evidence is published before claims. Read it last to minimize dangling
        # references during an in-progress audit; never search another run.
        records = {"assessments": self.blackboard.query_assessments(self.run_id),
            "findings": self.blackboard.query_findings(self.run_id),
            "evidence": self.blackboard.query_evidence(self.run_id)}
        for items in records.values():
            if any(item.run_id != self.run_id for item in items):
                raise ValueError("Blackboard returned records from another audit.")
            items.sort(key=lambda item: (item.created_at.isoformat(), item.id))
        validate_extensions(records)
        return {"records": records}

    def assemble_report(self, state):
        records = state["records"]
        assessments, originals, evidence = records["assessments"], records["findings"], records["evidence"]
        effective, historical_assessments, historical_findings, lineage_issues, decisions = effective_view(assessments, originals)
        findings, links, unresolved = report_findings(originals, evidence, assessments, effective=effective, historical=historical_findings)
        unresolved.extend(lineage_issues)
        current = [f for f in findings if f.lifecycle == "current"]
        coverage = coverage_projection(records, effective)
        indexes = {name: {item.id for item in items} for name, items in records.items()}
        incoming = {item.id: 0 for item in assessments}
        graph = {item.id: [child for child in item.assessment_ids if child in incoming] for item in assessments}
        for children in graph.values():
            for child in children:
                incoming[child] += 1
        pending = [key for key, count in incoming.items() if count == 0]
        visited = 0
        while pending:
            parent = pending.pop()
            visited += 1
            for child in graph[parent]:
                incoming[child] -= 1
                if incoming[child] == 0:
                    pending.append(child)
        if visited != len(assessments):
            unresolved.append("assessment_graph:cycle")
        for assessment in assessments:
            for field, target in (("finding_ids", "findings"), ("assessment_ids", "assessments"), ("evidence_ids", "evidence")):
                unresolved.extend(f"assessment:{assessment.id}:{field}:{item}"
                    for item in getattr(assessment, field) if item not in indexes[target])
        for finding in originals:
            unresolved.extend(f"finding:{finding.id}:assessment:{item}"
                for item in finding.assessment_ids if item not in indexes["assessments"])
        historical_prefixes = tuple([f"assessment:{i}:" for i in historical_assessments]
            + [f"finding:{i}:" for i in historical_findings])
        active_unresolved = [issue for issue in unresolved if not issue.startswith(historical_prefixes)] if historical_prefixes else unresolved
        contexts = [(item, item.details["audit_context"]) for item in evidence
            if isinstance(item.details.get("audit_context"), dict)]
        context = contexts[-1][1] if contexts else {}
        limitations = unique([*[value for item in assessments for value in item.limitations],
            *[value for item in evidence for value in item.details.get("investigation", {}).get("limitations", [])]])
        if unresolved:
            limitations.append("Existen referencias sin resolver en este blackboard; no se completan con datos de otras auditorías.")
        revisions = {(item.repository_id, item.commit, item.snapshot_hash) for item in assessments}
        revisions.update((context.get("repository_id"), item.commit, item.snapshot_hash) for item in evidence
            if not any(assessment.snapshot_hash == item.snapshot_hash for assessment in assessments))
        if len({(commit, snapshot) for _, commit, snapshot in revisions}) > 1:
            limitations.append("La auditoría contiene varias revisiones; sus evidencias se conservan por separado.")
        if not context:
            limitations.append("No consta contexto general del repositorio; el inventario técnico se limita a evidencias publicadas.")
        children = {identifier for item in effective for identifier in item.assessment_ids}
        roots = [item for item in effective if item.id not in children]
        if assessments and not roots:
            limitations.append("Las evaluaciones no tienen una raíz identificable; revisar referencias cíclicas.")
        status = evaluated_status(roots, current)
        if status == "not_evaluated":
            status = "partial" if evidence else "failed"
        if active_unresolved or (assessments and not roots) or len({(c, s) for _, c, s in revisions}) > 1:
            status = "partial" if records["evidence"] or findings else "failed"
        expected = context.get("manager_invocation_id")
        if expected and not any(item.invocation_id == expected for item in assessments):
            status = "partial"
            limitations.append("La ejecución principal aún no ha publicado una evaluación final.")
        outcomes = [item.details["audit_outcome"] for item in evidence
            if isinstance(item.details.get("audit_outcome"), dict)]
        if outcomes and outcomes[-1].get("status") in {"failed", "cancelled"}:
            status = "failed" if outcomes[-1]["status"] == "failed" else "partial"
            limitations.append("La ejecución terminó con estado " + outcomes[-1]["status"] + ".")
        attributes = self.attribute_results(effective, current)
        pending_coverage = [c for c in coverage if c.lifecycle == "current" and c.status in {"pending", "deferred", "skipped"}]
        if pending_coverage:
            if status == "completed":
                status = "partial"
            updated_attributes = []
            for attribute in attributes:
                updated_subs = []
                for sub in attribute.subcharacteristics:
                    affected = [c for c in pending_coverage if AGENT_CATEGORIES.get(c.agent_id) == (attribute.id, sub.id)]
                    if affected:
                        sub = sub.model_copy(update={"status": "partial", "conclusion": conclusion(sub.title, "partial",
                            [f for f in current if f.subcharacteristic == sub.id])})
                    updated_subs.append(sub)
                if any(s.status == "partial" for s in updated_subs):
                    attribute = attribute.model_copy(update={"status": "partial", "conclusion": conclusion(attribute.title, "partial",
                        [f for f in current if f.quality_attribute == attribute.id])})
                updated_attributes.append(attribute.model_copy(update={"subcharacteristics": updated_subs}))
            attributes = updated_attributes
        objectives = [statement(item.objective, item, "assessment") for item in roots if item.objective]
        if not objectives and context.get("objective"):
            objectives = [statement(context["objective"], contexts[-1][0], "evidence")]
        catalog = ReferenceCatalog({key: [item.model_dump(mode="json") for item in values] for key, values in records.items()})
        objective_topics = {"architecture_boundary": "los límites arquitectónicos", "responsibility": "la distribución de responsabilidades",
            "dependency_impact": "el impacto de las dependencias", "abstraction": "las abstracciones",
            "reuse_opportunity": "las oportunidades de reutilización", "component_adaptability": "las restricciones de adaptación"}
        specific = []
        for agent_id, topic in objective_topics.items():
            commitments = [row for row in coverage if row.agent_id == agent_id and row.lifecycle == "current"]
            if not commitments:
                continue
            subjects = unique(subject for row in commitments for subject in row.subject_ids)
            names = "; ".join(catalog.resolve(subject) for subject in subjects)
            refs = { (ref.record_type, ref.record_id): ref for row in commitments for ref in row.source_refs }
            specific.append(ReportStatement(text=f"Evaluar {topic}" + (f" en: {names}." if names else " en el alcance publicado.")
                + " El estado y las condiciones de cada compromiso se detallan en la matriz de cobertura.", source_refs=list(refs.values())))
        if not specific:
            specific = [statement(f"Evaluar {SUBCHARACTERISTICS[dimension][0].lower()} en el alcance publicado.", item, "assessment")
                for item in effective if item not in roots and (dimension := category(item)[1]) in SUBCHARACTERISTICS]
        counts = statistics(findings)
        risks, recommendations = self.risks_and_recommendations(current)
        summary = conclusion("Auditoría", status, current)
        problems = [f for f in current if f.verification_status == "verified" and f.disposition in {"defect", "contextual_risk"}]
        opportunities = [f for f in current if f.verification_status == "verified" and f.disposition in {"opportunity", "conditional_proposal"}]
        if problems:
            leading = min(problems, key=lambda f: (SEVERITIES.index(f.severity) if f.severity in SEVERITIES else len(SEVERITIES), f.id))
            summary += f" Resultado prioritario: {leading.title}. Consecuencia registrada: {leading.impact}"
            if leading.assessed_context:
                summary += " Contexto evaluado: " + leading.assessed_context
        if opportunities:
            summary += f" Se registran {len(opportunities)} oportunidades/propuestas; no se presentan como defectos confirmados."
        if pending_coverage:
            summary += f" Permanecen {len(pending_coverage)} compromisos sin resolver."
        issues = execution_diagnostics(assessments, evidence, originals)
        summaries = self.executive_results(records, attributes, findings, files_count=len({
            item.source for item in evidence if item.kind == "source"}), issues=issues)
        criteria = {item.criterion.model_dump_json(): item.criterion for item in originals}
        files = sorted({item.source for item in evidence if item.kind == "source"})
        scope_limitations = [
            f"La evidencia de código publicada abarca {len(files)} archivos distintos; no acredita una inspección exhaustiva del repositorio.",
            "Las conclusiones se limitan al análisis publicado; no se afirman aislamiento en ejecución ni resultados de pruebas dinámicas no registrados.",
        ]
        if status != "completed":
            scope_limitations.append("La auditoría está incompleta; sus resultados no permiten emitir una conclusión de conformidad global.")
        if issues:
            if status != "completed":
                scope_limitations.append("Los motivos registrados incluyen antecedentes y ejecuciones pendientes; su vigencia se detalla por compromiso y evaluación.")
            scope_limitations.append("Los diagnósticos técnicos, hipótesis pendientes y limitaciones originales se conservan en los anexos.")
        if active_unresolved:
            scope_limitations.append("Existen referencias sin resolver; los resultados afectados se mantienen inconclusos.")
        if not context:
            scope_limitations.append("No consta contexto general del repositorio publicado en el blackboard.")
        components = sorted({component for item in current for component in item.components}
            | {subject for row in coverage if row.lifecycle == "current" for subject in row.subject_ids})
        targets = unique([*[target for item in assessments for target in item.targets], *context.get("targets", [])])
        exclusions = list(context.get("exclusions", []))
        scope = {item.id: [sub.id for sub in item.subcharacteristics if sub.status != "not_evaluated"]
            for item in attributes if item.status != "not_evaluated"}
        for item in assessments:
            if isinstance(item.scope, dict):
                exclusions.extend(f"Dimensión no soportada: {name}" for name in item.scope.get("unsupported", []))
        raw = {name: [item.model_dump(mode="json") for item in items] for name, items in records.items()}
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        for assessment in effective:
            decisions.append(decision("effective_assessment_selection", "current",
                "No existe una continuación acumulada válida que sustituya esta evaluación; su alcance y sus brechas permanecen vigentes.",
                [reference(assessment, "assessment")], ["quality_results.attributes", "identification.status"]))
        for link in links:
            decisions.append(decision("explicit_group_reference_expansion", "resolved",
                "La relación se resolvió a sus contribuciones originales mediante identidades de grupo e invocación: "
                    + ", ".join(link["finding_ids"]), link["source_refs"], ["consolidated_risks.relationships"]))
        for item in findings:
            included = any(item.id in r.finding_ids for r in risks)
            decisions.append(decision("finding_documentary_disposition", "risk" if included else item.disposition,
                f"Estado documental: {item.verification_status}; vigencia: {item.lifecycle}; "
                + ("Perjuicio/contexto respaldado por un hallazgo vigente verificado." if included else
                   "No reúne la condición de riesgo vigente verificado o es una oportunidad/fortaleza.")
                + (" Problemas: " + ", ".join(item.validation_issues) if item.validation_issues else ""),
                item.source_refs, [f"quality_results.findings/{item.id}", "consolidated_risks", "recommendations_and_improvement_plan"]))
        for row in coverage:
            decisions.append(decision("host_resolved_commitment", row.status,
                f"Hipótesis {row.hypothesis_id}: {row.final_hypothesis_status}; vigencia: {row.lifecycle}. "
                + (", ".join(row.validation_issues) or "Se conserva la resolución del host y la disponibilidad de evidencia publicada."),
                row.source_refs, ["annexes_and_traceability.coverage_commitments", "quality_results.attributes"]))
        decisions.append(decision("audit_documentary_status", status,
            f"Estados raíz publicados: {[r.status for r in roots]}; hallazgos vigentes inconclusos: "
            f"{sum(f.verification_status == 'inconclusive' for f in current)}; compromisos pendientes: {len(pending_coverage)}; "
            f"referencias vigentes sin resolver: {len(active_unresolved)}; revisiones: {len(revisions)}. "
            + (f"Resultado de ejecución publicado: {outcomes[-1].get('status')}." if outcomes else "No consta un resultado de ejecución adicional."),
            [reference(a, "assessment") for a in roots], ["identification.status", "executive_summary.conclusion", "general_conclusions"]))
        decisions.append(decision("human_readable_objectives_and_references", "projected",
            "Los objetivos específicos describen las áreas y sujetos de los compromisos vigentes. "
            "Los nombres proceden exclusivamente de metadatos publicados; una identidad ambigua o ausente conserva una etiqueta sin nombre. "
            "Los objetivos operativos originales y los identificadores completos permanecen en el snapshot y los registros de ejecución.",
            list({(ref.record_type, ref.record_id): ref for row in coverage for ref in row.source_refs}.values()),
            ["objectives_and_scope.specific_objectives", "annexes_and_traceability.reference_labels"]))
        generation = ReportGeneration(generation_id=uuid4().hex, generator_version=GENERATOR_VERSION, generated_at=self.issued_at,
            source_digest=digest, source_snapshot={"run_id": self.run_id, **raw},
            effective_assessment_ids=[a.id for a in effective], historical_assessment_ids=sorted(historical_assessments),
            decisions=decisions, issues=unique([*unresolved, *[f"coverage:{row.invocation_id}:{row.hypothesis_id}:{','.join(row.subject_ids)}:{row.status}"
                for row in pending_coverage]]))
        names = {item.repository_id for item in assessments} | {context.get("repository_id")}
        names.discard(None)
        dates = [item.created_at for items in records.values() for item in items]
        report = SoftwareAuditReport(
            identification=ReportIdentification(audit_id=self.run_id,
                project_name=next(iter(names)) if len(names) == 1 else None,
                repository_location=context.get("repository_location"), repository_url=context.get("repository_url"),
                revisions=[RepositoryRevision(repository_id=name, commit=commit, snapshot_hash=snapshot)
                    for name, commit, snapshot in sorted(revisions, key=lambda row: tuple(value or "" for value in row))],
                executed_at=context.get("execution_started_at") or (min(dates) if dates else None),
                issued_at=self.issued_at, status=status, source_digest=digest),
            executive_summary=ExecutiveSummary(objective=objectives,
                evaluated_attributes=[item.id for item in attributes if item.status != "not_evaluated"],
                principal_results=summaries, findings=counts, principal_risk_ids=[item.id for item in risks[:5]], conclusion=summary),
            objectives_and_scope=AuditScope(general_objectives=objectives, specific_objectives=specific,
                attributes_and_subcharacteristics=scope, included_components=components, inspected_files=files,
                declared_targets=targets, exclusions=unique(exclusions), limitations=scope_limitations),
            methodology_and_criteria=AuditMethodology(applied_criteria=list(criteria.values()),
                static_analysis=["Inspección estática y consultas de código registradas por los agentes."] if evidence else [],
                dynamic_analysis=self.recorded_statements(evidence, "dynamic_analysis"),
                tools=sorted({item.details["tool_name"] for item in evidence if isinstance(item.details.get("tool_name"), str)}),
                finding_validation=["Se conserva el estado de revisión publicado, sin elevar hallazgos inconclusos o descartados.",
                    "Se verifican referencias en la misma auditoría, identidad de revisión y atribución al commit.",
                    "Conflictos entre revisores y falta de soporte técnico producen resultados inconclusos."],
                severity_criteria={"critical": "Prioridad urgente según la severidad publicada por el auditor.",
                    "high": "Prioridad alta según la severidad publicada por el auditor.",
                    "medium": "Prioridad media según la severidad publicada por el auditor.",
                    "low": "Prioridad baja según la severidad publicada por el auditor.",
                    "info": "Observación informativa; no implica por sí misma un defecto.",
                    "undetermined": "Severidad no determinada; el informe no inventa umbrales."},
                limitations=["El informe documenta resultados publicados; no ejecuta pruebas ni certifica cumplimiento de ISO.",
                    "Las escalas de severidad proceden de los agentes; no se infieren umbrales normativos.",
                    "Los registros se leen por auditoría; el blackboard actual no ofrece una transacción de lectura global."]),
            software_description=self.software_description(contexts, files),
            quality_results=QualityResults(attributes=attributes, findings=findings),
            consolidated_risks=ConsolidatedRiskAnalysis(findings=counts, risks=risks,
                relationships=[FindingRelationship(**item) for item in links],
                prioritization_method="Solo perjuicios o riesgos contextualizados de hallazgos vigentes verificados, ordenados por severidad publicada. "
                    "Las oportunidades y propuestas condicionales no se convierten en defectos; no se estima probabilidad ni se suman puntuaciones."),
            general_conclusions=AuditConclusions(by_attribute=[ReportStatement(text=item.conclusion,
                source_refs=[reference(assessment, "assessment") for assessment in assessments
                    if category(assessment)[0] == item.id]) for item in attributes if item.status != "not_evaluated"],
                strengths=[*self.recorded_statements(evidence, "strengths"),
                    *[ReportStatement(text=item.description, source_refs=item.source_refs) for item in current
                        if item.verification_status == "verified" and item.disposition == "strength"]],
                weaknesses=[ReportStatement(text=item.impact, source_refs=item.source_refs)
                    for item in current if item.verification_status == "verified" and item.disposition in {"defect", "contextual_risk"}],
                critical_finding_ids=[item.id for item in problems
                    if item.severity in {"critical", "high"}], limitations=scope_limitations, general_conclusion=summary),
            recommendations_and_improvement_plan=recommendations,
            annexes_and_traceability=self.annexes(records, list(criteria.values()), unresolved, limitations).model_copy(
                update={"coverage_commitments": coverage, "generation": generation, "reference_labels": catalog.labels}))
        return {"report": report}

    def attribute_results(self, assessments, findings):
        attributes = unique([*ATTRIBUTE_TITLES, *[category(item)[0] for item in assessments],
            *[item.quality_attribute for item in findings]])
        result = []
        for attribute in attributes:
            selected = [item for item in assessments if category(item)[0] == attribute]
            claims = [item for item in findings if item.quality_attribute == attribute]
            dimensions = unique([*(SUBCHARACTERISTICS if attribute == "maintainability" else []),
                *[category(item)[1] for item in selected if category(item)[1] != "unspecified"],
                *[item.subcharacteristic for item in claims]])
            subs = []
            for dimension in dimensions:
                related = [item for item in selected if category(item)[1] == dimension]
                subclaims = [item for item in claims if item.subcharacteristic == dimension]
                status = evaluated_status(related, subclaims)
                title, topics = (SECURITY_SUBCHARACTERISTICS if attribute == "security" else SUBCHARACTERISTICS).get(dimension, (dimension, []))
                subs.append(SubcharacteristicResult(id=dimension, title=title, status=status, evaluation_topics=topics,
                    assessments=[statement(item.summary, item, "assessment") for item in related if item.summary],
                    finding_ids=[item.id for item in subclaims], conclusion=conclusion(title, status, subclaims),
                    limitations=unique(value for item in related for value in item.limitations)))
            status = evaluated_status(selected, claims)
            title = ATTRIBUTE_TITLES.get(attribute, attribute)
            result.append(AttributeResult(id=attribute, title=title, status=status,
                summary=[statement(item.summary, item, "assessment") for item in selected if item.summary],
                subcharacteristics=subs, conclusion=conclusion(title, status, claims)))
        return result

    @staticmethod
    def executive_results(records, attributes, findings, *, files_count, issues):
        """Generate a bounded narrative from facts, rather than copying supervisor prose."""
        results = []
        sources = {item.id: reference(item, kind) for kind, items in
            (("assessment", records["assessments"]), ("evidence", records["evidence"]), ("finding", records["findings"]))
            for item in items}
        for attribute in attributes:
            if attribute.status == "not_evaluated":
                continue
            evaluated = [sub.title for sub in attribute.subcharacteristics if sub.status != "not_evaluated"]
            unexamined = [sub.title for sub in attribute.subcharacteristics if sub.status == "not_evaluated"]
            text = f"{attribute.title}: el alcance publicado incluye {', '.join(evaluated) or 'una evaluación sin subcaracterísticas declaradas'}."
            if unexamined:
                text += f" No se evaluaron {', '.join(unexamined)}."
            results.append(ReportStatement(text=text, source_refs=[reference(item, "assessment")
                for item in records["assessments"] if category(item)[0] == attribute.id]))
        counts = statistics(findings)
        results.append(ReportStatement(text=(f"Se dispone de evidencia de código de {files_count} archivos distintos. "
            f"De {counts.total} registros de hallazgos, {counts.by_verification['verified']} están verificados, "
            f"{counts.by_verification['inconclusive']} permanecen inconclusos y {counts.by_verification['discarded']} fueron descartados. "
            "Los resultados inconclusos o descartados no se consideran defectos confirmados."),
            source_refs=[sources[item.id] for item in records["findings"]]))
        results.append(ReportStatement(text=f"Se consideran vigentes {counts.active_total} registros; los históricos se conservan sin duplicar acciones.",
            source_refs=[sources[item.id] for item in records["findings"]]))
        for item in sorted((item for item in findings if item.verification_status == "verified" and item.lifecycle == "current"),
                key=lambda item: (item.disposition not in {"defect", "contextual_risk"},
                    SEVERITIES.index(item.severity) if item.severity in SEVERITIES else len(SEVERITIES), item.id))[:3]:
            label = {"strength": "Fortaleza", "conditional_proposal": "Propuesta condicionada", "opportunity": "Oportunidad",
                "contextual_risk": "Riesgo contextualizado", "defect": "Perjuicio verificado", "observation": "Observación verificada"}[item.disposition]
            results.append(ReportStatement(text=f"{label}: "
                f"{item.title}. Impacto registrado: {item.impact}"
                + (" Contexto: " + item.assessed_context if item.assessed_context else "")
                + (" Condiciones: " + "; ".join(item.conditions) if item.conditions else ""), source_refs=item.source_refs))
        if issues:
            incidents = unique(incident for issue in issues for incident in issue.incidents)
            reasons = unique(issue.explanation for issue in issues)
            results.append(ReportStatement(text=(f"Se conservan {len(issues)} registros de ejecuciones incompletas o fallidas, "
                "incluidos antecedentes y niveles de supervisión. Motivos registrados: " + " ".join(reasons[:3])
                + (" Incidencias registradas: " + " ".join(incidents) if incidents else "")
                + " La selección de evaluaciones y la matriz de compromisos distinguen el trabajo vigente del histórico reparado. "
                "Estas incidencias no constituyen defectos del software evaluado."),
                source_refs=list({identifier: sources[identifier] for issue in issues
                    for identifier in issue.source_record_ids if identifier in sources}.values())))
        return results

    @staticmethod
    def risks_and_recommendations(findings):
        risks, recommendations = [], []
        verified = sorted((item for item in findings if item.verification_status == "verified" and item.lifecycle == "current"
            and item.disposition in {"defect", "contextual_risk", "opportunity", "conditional_proposal"}),
            key=lambda item: (SEVERITIES.index(item.severity) if item.severity in SEVERITIES else len(SEVERITIES), item.id))
        for item in verified:
            priority = PRIORITIES.get(item.severity, "undetermined")
            qualifications = {key: getattr(item, key) for key in
                ("assessed_context", "sharing_boundary", "conditions", "assumptions", "unknowns", "limitations")}
            if item.disposition in {"defect", "contextual_risk"}:
                risks.append(ReportRisk(id=f"risk:{item.id}", finding_ids=[item.id], components=item.components,
                    description=item.impact, severity=item.severity, priority=priority, **qualifications,
                    risk_type="contextual" if item.disposition == "contextual_risk" else "verified_harm"))
            if item.recommendation:
                action_type = {"defect": "correction", "contextual_risk": "context_validation", "opportunity": "opportunity_assessment",
                    "conditional_proposal": "conditional_assessment"}[item.disposition]
                qualified = item.disposition != "defect"
                prefix = {"conditional_proposal": "Evaluar la propuesta condicionada antes de autorizar cambios. ",
                    "opportunity": "Evaluar la oportunidad sin presumir un defecto. ",
                    "contextual_risk": "Validar el contexto y los supuestos de adaptación. "}.get(item.disposition, "")
                recommendations.append(ImprovementRecommendation(id=f"recommendation:{item.id}", finding_ids=[item.id],
                    action=prefix + item.recommendation, technical_justification=item.description, priority=priority,
                    action_type=action_type, **qualifications,
                    expected_benefit=("Beneficio sujeto a validación: " if qualified else "Mitigar el impacto documentado: ") + item.impact,
                    proposed_verification_criterion=(f"Reevaluar el criterio «{item.criterion.description}» en "
                        f"{', '.join(item.components)}; aportar evidencia y revisión "
                        + ("que validen el contexto, las condiciones y la conveniencia de la propuesta." if qualified
                            else "que confirmen la corrección dentro de ese alcance."))))
        return risks, recommendations

    @staticmethod
    def recorded_statements(evidence, key):
        return [statement(text, item, "evidence") for item in evidence
            for text in item.details.get("report_facts", {}).get(key, []) if isinstance(text, str)]

    @staticmethod
    def software_description(contexts, inspected_files):
        if not contexts:
            return SoftwareDescription(repository_structure=unique(path.split("/")[0] for path in inspected_files),
                limitations=["No consta un inventario general ni una arquitectura validada; no se deducen del nombre de las carpetas."])
        source, context = contexts[-1]
        return SoftwareDescription(description=statement(context["description"], source, "evidence") if context.get("description") else None,
            languages=context.get("languages", []), technologies=context.get("technologies", []),
            repository_structure=context.get("repository_structure", []), modules=context.get("modules", []),
            architecture=[statement(text, source, "evidence") for text in context.get("validated_architecture", [])],
            dependencies=context.get("dependencies", []), runtime_environment=context.get("runtime_environment", []),
            limitations=["La detección tecnológica y las señales estructurales no demuestran una arquitectura ni ejecución dinámica.",
                *context.get("limitations", [])], source_refs=[reference(source, "evidence")])

    @staticmethod
    def annexes(records, criteria, unresolved, limitations):
        executions = {}
        for item in records["assessments"]:
            executions[item.invocation_id] = ExecutionTrace(agent_id=item.agent_id, invocation_id=item.invocation_id,
                assessment_ids=[item.id], status=item.status, termination_reason=item.termination_reason,
                consumption=item.consumption.model_dump(mode="json"), limitations=list(item.limitations),
                unresolved_results=list(item.gaps), recorded_results={"conclusions": list(item.conclusions),
                    "coverage": item.coverage, "interpretation": item.interpretation,
                    "consolidated_findings": list(item.consolidated_findings)})
        for item in [*records["evidence"], *records["findings"]]:
            investigation = item.details.get("investigation")
            if item.invocation_id in executions or not isinstance(investigation, dict):
                continue
            executions[item.invocation_id] = ExecutionTrace(agent_id=item.agent_id, invocation_id=item.invocation_id,
                assessment_ids=[], status=investigation.get("status"), termination_reason=investigation.get("termination_reason"),
                consumption={key: investigation[key] for key in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")
                    if key in investigation}, limitations=investigation.get("limitations", []),
                unresolved_results=[value for value in investigation.get("hypotheses", [])
                    if value.get("status") in {"pending", "inconclusive"}]
                    + [{"missing_information": value} for value in investigation.get("missing_information", [])],
                recorded_results={key: value for key, value in investigation.items()
                    if key not in {"findings", "evidence", "model_calls", "tool_calls", "accounted_tokens", "estimated_tokens"}})
        # A failed child may have published neither evidence nor findings. Its
        # parent's retained invocation is still a traceable execution record.
        for item in execution_records(records["assessments"], records["evidence"], records["findings"]):
            if item["invocation_id"] in executions:
                continue
            result = item["report"]
            executions[item["invocation_id"]] = ExecutionTrace(agent_id=item["agent_id"], invocation_id=item["invocation_id"],
                assessment_ids=[], status=item["status"], termination_reason=result.get("termination_reason"),
                consumption=result.get("consumption", {key: result[key] for key in
                    ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens") if key in result}),
                limitations=[*result.get("limitations", []), *([item["error"]] if item["error"] else [])],
                unresolved_results=[{"missing_information": text} for text in result.get("missing_information", [])],
                recorded_results={key: value for key, value in result.items() if key not in {"findings", "evidence", "invocations", "assessments"}})
        return AuditAnnexes(evidence_inventory=[ReportEvidence(**{
            key: getattr(item, key) for key in ("id", "kind", "source", "content", "snapshot_hash", "commit",
                "commit_verification", "git_blob_id", "file_id", "content_hash", "symbol_ids", "start_line", "end_line", "tool_call_id")
        }, provenance=reference(item, "evidence")) for item in records["evidence"]],
            assessments=[reference(item, "assessment") for item in records["assessments"]],
            executions=list(executions.values()), metrics_and_tool_results=[
                {"evidence_id": item.id, "result": item.details[key]} for item in records["evidence"]
                for key in ("metrics", "tool_result", "measurement") if key in item.details],
            diagrams_and_graphs=[{"evidence_id": item.id, "artifact": item.details[key]} for item in records["evidence"]
                for key in ("diagram", "dependency_graph") if key in item.details],
            participants=sorted({item.agent_id for items in records.values() for item in items}),
            tools=sorted({item.details["tool_name"] for item in records["evidence"] if isinstance(item.details.get("tool_name"), str)}),
            tool_call_ids=sorted({item.tool_call_id for item in records["evidence"]}), additional_criteria=criteria,
            unresolved_references=unique(unresolved), limitations=limitations,
            execution_issues=execution_diagnostics(records["assessments"], records["evidence"], records["findings"]))

    @staticmethod
    def validate_traceability(state):
        report = SoftwareAuditReport.model_validate(state["report"].model_dump(mode="json"))
        finding_ids = {item.id for item in report.quality_results.findings}
        evidence_ids = {item.id for item in report.annexes_and_traceability.evidence_inventory}
        if any(not set(item.evidence_ids) <= evidence_ids for item in report.quality_results.findings):
            raise ValueError("Report evidence reference is unresolved.")
        linked = [*report.recommendations_and_improvement_plan, *report.consolidated_risks.risks,
            *report.consolidated_risks.relationships]
        if any(not set(item.finding_ids) <= finding_ids for item in linked):
            raise ValueError("Report finding reference is unresolved.")
        verified = {item.id for item in report.quality_results.findings if item.verification_status == "verified"}
        if any(not set(item.finding_ids) <= verified for item in [
                *report.recommendations_and_improvement_plan, *report.consolidated_risks.risks]):
            raise ValueError("Unverified findings cannot be presented as confirmed risks or corrections.")
        generation = report.annexes_and_traceability.generation
        if generation is not None:
            known = {(kind, item["id"]): item for kind, key in
                (("finding", "findings"), ("evidence", "evidence"), ("assessment", "assessments"))
                for item in generation.source_snapshot[key]}

            def check(value):
                if isinstance(value, RecordReference):
                    source = known.get((value.record_type, value.record_id))
                    if source is None or (source["agent_id"], source["invocation_id"]) != (value.agent_id, value.invocation_id):
                        raise ValueError("Report provenance reference does not match its original record.")
                elif isinstance(value, BaseModel):
                    for key in type(value).model_fields:
                        check(getattr(value, key))
                elif isinstance(value, list):
                    for item in value:
                        check(item)
            check(report)
            raw = {key: generation.source_snapshot[key] for key in ("assessments", "findings", "evidence")}
            digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if digest != generation.source_digest or digest != report.identification.source_digest:
                raise ValueError("Report source digest mismatch.")
            for item in report.annexes_and_traceability.evidence_inventory:
                source = known.get(("evidence", item.id))
                projection = item.model_dump(mode="json", exclude={"provenance"})
                if source is None or any(source.get(key) != value for key, value in projection.items()):
                    raise ValueError("Report evidence inventory differs from the captured source.")
            original_ids = {a["id"] for a in generation.source_snapshot["assessments"]}
            if set(generation.effective_assessment_ids) | set(generation.historical_assessment_ids) != original_ids:
                raise ValueError("Report assessment selection is incomplete.")
            if any(not set(row.evidence_ids) <= evidence_ids for row in report.annexes_and_traceability.coverage_commitments):
                raise ValueError("Coverage evidence is unresolved.")
            by_id = {f.id: f for f in report.quality_results.findings}
            for risk in report.consolidated_risks.risks:
                if any(by_id[i].lifecycle != "current" or by_id[i].disposition not in {"defect", "contextual_risk"} for i in risk.finding_ids):
                    raise ValueError("Historical findings and opportunities cannot become current risks.")
            for derived in [*report.consolidated_risks.risks, *report.recommendations_and_improvement_plan]:
                for identifier in derived.finding_ids:
                    finding = by_id[identifier]
                    if finding.lifecycle != "current" or any(getattr(derived, key) != getattr(finding, key) for key in
                            ("conditions", "assumptions", "unknowns", "assessed_context", "sharing_boundary", "limitations")):
                        raise ValueError("Derived conclusion lost its source qualifications.")
            generation = generation.model_copy(update={"validation_status": "passed", "validation_checks": [
                "same_run_record_identity", "record_reference_provenance", "source_digest", "source_evidence_inventory", "assessment_selection", "finding_evidence",
                "coverage_evidence", "verified_current_risks_and_actions", "preserved_qualifications"]})
            report = report.model_copy(update={"annexes_and_traceability": report.annexes_and_traceability.model_copy(
                update={"generation": generation})})
        return {"report": report}
