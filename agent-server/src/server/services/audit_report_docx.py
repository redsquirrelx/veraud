"""Deterministic presentation of the canonical audit JSON as an in-memory DOCX."""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from lxml.etree import Element

from ..agents.audit_report.config import ReportPresentationConfig
from ..agents.audit_report.references import ReferenceCatalog
from ..agents.schemes.report import SoftwareAuditReport

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_RENDERER_VERSION = "2.0.0"
LABELS = {
    "completed": "Completada", "partial": "Parcial", "failed": "Fallida", "not_evaluated": "No evaluado",
    "verified": "Verificado", "inconclusive": "Inconcluso", "discarded": "Descartado",
    "critical": "Crítica", "high": "Alta", "medium": "Media", "low": "Baja", "info": "Informativa",
    "urgent": "Urgente", "undetermined": "No determinada",
    "maintainability": "Mantenibilidad", "security": "Seguridad", "functional_adequacy": "Adecuación funcional",
    "modularity": "Modularidad", "reusability": "Reusabilidad", "analysability": "Analizabilidad",
    "modifiability": "Modificabilidad", "testability": "Capacidad de prueba", "complete": "Completada",
    "problem": "Problema", "observation": "Observación", "strength": "Fortaleza",
    "violation": "Incumplimiento", "design_observation": "Observación de diseño",
    "exact": "Coincidencia exacta", "unverified": "No verificado", "snapshot_only": "Solo snapshot",
    "finding": "Hallazgo", "assessment": "Evaluación", "evidence": "Evidencia",
    "accepted": "Aceptado", "rejected": "Rechazado", "insufficient_evidence": "Evidencia insuficiente",
    "explicit": "Explícito", "heuristic": "Heurístico", "source": "Código fuente",
}
FIELD_LABELS = {
    "id": "Identificador", "agent_id": "Agente", "invocation_id": "Invocación",
    "record_type": "Tipo de registro", "record_id": "Registro", "finding_id": "Hallazgo",
    "finding_ids": "Hallazgos", "finding_refs": "Referencias de hallazgos", "evidence_ids": "Evidencias",
    "evidence_id": "Evidencia", "assessment_ids": "Evaluaciones", "source": "Archivo o fuente",
    "source_refs": "Fuentes", "kind": "Tipo", "status": "Estado", "description": "Descripción",
    "name": "Nombre", "version": "Versión", "path": "Ruta", "file_path": "Archivo",
    "project": "Proyecto", "project_id": "Proyecto", "framework": "Framework", "language": "Lenguaje",
    "runtime": "Entorno", "manager": "Gestor", "package": "Paquete", "scope": "Alcance",
    "manifest_path": "Manifiesto", "manifest": "Manifiesto", "source_file": "Archivo de origen",
    "ecosystem": "Ecosistema", "constraint": "Restricción de versión", "category": "Categoría",
    "termination_reason": "Motivo de terminación", "consumption": "Consumo de recursos",
    "model_calls": "Llamadas al modelo", "tool_calls": "Llamadas a herramientas",
    "accounted_tokens": "Tokens contabilizados", "estimated_tokens": "Tokens estimados",
    "model_calls_estimated": "Llamadas estimadas", "input_tokens": "Tokens de entrada",
    "output_tokens": "Tokens de salida", "duration_seconds": "Duración (segundos)",
    "seconds": "Duración (segundos)", "tool": "Herramienta", "call_id": "Llamada",
    "result": "Resultado", "measurement": "Medición", "metrics": "Métricas",
    "limitations": "Limitaciones", "unresolved_results": "Resultados pendientes",
    "recorded_results": "Resultados registrados", "hypotheses": "Hipótesis", "question": "Pregunta",
    "rationale": "Justificación", "conclusion": "Conclusión", "summary": "Resumen",
    "missing_information": "Información pendiente", "criterion": "Criterio", "criterion_id": "Criterio",
    "origin": "Origen", "provenance": "Procedencia", "justification": "Justificación",
    "recommendation": "Recomendación", "severity": "Severidad", "confidence": "Confianza",
    "components": "Componentes", "component_id": "Componente", "title": "Título",
    "content": "Contenido registrado", "snapshot_hash": "Hash del snapshot", "commit": "Commit",
    "commit_verification": "Verificación del commit", "git_blob_id": "Blob Git", "file_id": "Archivo (ID)",
    "content_hash": "Hash del contenido", "symbol_ids": "Símbolos", "start_line": "Línea inicial",
    "end_line": "Línea final", "tool_call_id": "Llamada de herramienta", "artifact": "Artefacto",
    "validation_status": "Estado de validación", "review_rationale": "Justificación de revisión",
    "modularity_impact": "Impacto en modularidad", "interpretation": "Interpretación",
    "claim_checks": "Validaciones de afirmaciones", "critical_review": "Revisión crítica",
    "contributions": "Contribuciones", "reference": "Referencia", "finding": "Hallazgo",
    "coverage": "Cobertura", "conclusions": "Conclusiones", "consolidated_findings": "Hallazgos consolidados",
    "evidence_refs": "Referencias de evidencia", "source_record_ids": "Registros de origen",
    "version_constraint": "Versión declarada", "resolved_version": "Versión resuelta",
    "resolved_versions": "Versiones resueltas", "environment_marker": "Condición de entorno",
    "detection": "Método de detección", "image": "Imagen", "build_context": "Contexto de construcción",
    "ports": "Puertos",
    "deferred_stages": "Etapas pendientes del proveedor", "node": "Etapa", "reason": "Motivo",
    "http_status": "Estado HTTP", "retry_after_seconds": "Espera solicitada (segundos)", "attempts": "Intentos",
}
INVALID_XML = re.compile(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")


def text(value):
    if value is None or value == "":
        return "No consta"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return INVALID_XML.sub("\ufffd", str(value))


def field_label(key):
    return FIELD_LABELS.get(key, LABELS.get(key, key.replace("_", " ").capitalize()))


@dataclass(frozen=True)
class ReferenceTarget:
    identifier: str
    caption: str | None = None


@dataclass(frozen=True)
class LiteralText:
    value: str | None


class ReportDocument:
    def __init__(self, report, config=None):
        self.report = report
        self.config = config or ReportPresentationConfig()
        self.doc = Document()
        self.targets = {}
        self.aliases = {}
        self.bookmarks = set()
        self.execution_targets = {}
        self.used_entity_targets = set()
        # The captured source snapshot is retained in JSON, not walked a second
        # time just to label Word links. Resolved source labels are already kept.
        self.reference_labels = dict(ReferenceCatalog(report.model_dump(mode="json",
            exclude={"annexes_and_traceability": {"generation"}})).labels)
        self.reference_labels.update(report.annexes_and_traceability.reference_labels)
        self.reference_labels[report.identification.audit_id] = "Auditoría actual"
        self.reference_labels[report.identification.source_digest] = "Huella de los registros de entrada"
        for number, revision in enumerate(report.identification.revisions, 1):
            self.reference_labels[revision.snapshot_hash] = f"Snapshot auditado S{number:03d}"
            if revision.commit:
                self.reference_labels[revision.commit] = f"Revisión auditada R{number:03d}"
        generation = report.annexes_and_traceability.generation
        if generation:
            self.reference_labels[generation.generation_id] = "Generación de este informe"
        groups = (("Hallazgo", "H", report.quality_results.findings),
            ("Evidencia", "E", report.annexes_and_traceability.evidence_inventory),
            ("Evaluación", "A", report.annexes_and_traceability.assessments),
            ("Riesgo", "R", report.consolidated_risks.risks),
            ("Acción", "M", report.recommendations_and_improvement_plan),
            ("Ejecución", "X", report.annexes_and_traceability.executions))
        for title, prefix, items in groups:
            for number, item in enumerate(items, 1):
                identifier = getattr(item, "id", None) or getattr(item, "record_id", None) or item.invocation_id
                if prefix == "X":
                    self.execution_targets[identifier] = "execution:" + identifier
                    identifier = "execution:" + identifier
                label = f"{title} {prefix}{number:03d}"
                self.targets[identifier] = (label, f"ref_{prefix}{number:03d}", len(self.targets) + 1)
                self.aliases[identifier] = identifier
                if prefix == "X":
                    self.aliases.setdefault(item.invocation_id, identifier)
                if prefix in {"H", "E", "A"}:
                    kind = {"H": "finding", "E": "evidence", "A": "assessment"}[prefix]
                    self.aliases[f"{kind}:{identifier}"] = identifier
        self.entity_targets = []
        for identifier, label in sorted(self.reference_labels.items()):
            if identifier in self.aliases or not identifier:
                continue
            number = len(self.entity_targets) + 1
            self.targets[identifier] = (label, f"ref_entity_{number}", len(self.targets) + 1)
            self.aliases[identifier] = identifier
            self.entity_targets.append(identifier)
        # Match longest IDs first, and never rewrite a substring of a path/name.
        self.reference_pattern = (re.compile(r"(?<![\w])(?:" + "|".join(re.escape(key)
            for key in sorted(self.aliases, key=lambda key: (-len(key), key))) + r")(?![\w])") if self.aliases else None)
        section = self.doc.sections[0]
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.top_margin = section.bottom_margin = Cm(2)
        section.left_margin = section.right_margin = Cm(2.2)
        style = self.doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(10)
        style.paragraph_format.space_after = Pt(6)
        for name in ("Heading 1", "Heading 2", "Heading 3"):
            self.doc.styles[name].font.color.rgb = RGBColor.from_string("17365D")
        props = self.doc.core_properties
        props.title = text(report.identification.title)
        props.subject = "Auditoría " + text(report.identification.audit_id)
        props.author = "Veraud"
        props.last_modified_by = "Veraud"
        props.version = DOCX_RENDERER_VERSION
        issued_at = report.identification.issued_at
        props.created = props.modified = issued_at.replace(tzinfo=UTC) if issued_at.tzinfo is None else issued_at.astimezone(UTC)
        props.identifier = report.identification.source_digest
        section.header.paragraphs[0].text = "Veraud · Informe de auditoría de calidad del software"
        section.footer.paragraphs[0].text = "Veraud · Auditoría actual"

    def heading(self, title, level=1, target=None, *, collapsed=False):
        paragraph = self.doc.add_heading("", level=level)
        self.linked_text(paragraph, title)
        if collapsed:
            paragraph._p.get_or_add_pPr().append(Element("{http://schemas.microsoft.com/office/word/2012/wordml}collapsed"))
        if target:
            self.bookmark(paragraph, target)

    def bookmark(self, paragraph, identifier):
        if identifier in self.bookmarks:
            return
        _, anchor, number = self.targets[identifier]
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), str(number))
        start.set(qn("w:name"), anchor)
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), str(number))
        paragraph._p.insert(1 if paragraph._p.pPr is not None else 0, start)
        paragraph._p.append(end)
        self.bookmarks.add(identifier)

    def hyperlink(self, paragraph, identifier):
        if identifier in self.reference_labels:
            self.used_entity_targets.add(identifier)
        label, anchor, _ = self.targets[identifier]
        link = OxmlElement("w:hyperlink")
        link.set(qn("w:anchor"), anchor)
        link.set(qn("w:history"), "1")
        link.set(qn("w:tooltip"), text("ID de origen: " + identifier))
        run = OxmlElement("w:r")
        properties = OxmlElement("w:rPr")
        color = OxmlElement("w:color")
        color.set(qn("w:val"), "0563C1")
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        properties.extend([color, underline])
        run.append(properties)
        value = OxmlElement("w:t")
        value.text = label
        run.append(value)
        link.append(run)
        paragraph._p.append(link)

    def linked_text(self, paragraph, value):
        value = text(value)
        if len(value) > self.config.max_text_characters:
            value = value[:self.config.max_text_characters] + "… [Texto abreviado; completo en el JSON canónico.]"
        if self.reference_pattern is None:
            paragraph.add_run(value)
            return
        offset = 0
        for match in self.reference_pattern.finditer(value):
            if match.start() > offset:
                paragraph.add_run(value[offset:match.start()])
            self.hyperlink(paragraph, self.aliases[match.group()])
            offset = match.end()
        if offset < len(value):
            paragraph.add_run(value[offset:])

    def paragraph(self, value):
        self.value(self.doc, value)

    def write(self, container, value, style=None, *, linked=True):
        if container is not self.doc and len(container.paragraphs) == 1 and not container.tables and not container.paragraphs[0].text:
            paragraph = container.paragraphs[0]
            paragraph.clear()
            if style:
                paragraph.style = style
        else:
            paragraph = container.add_paragraph(style=style)
        if linked:
            self.linked_text(paragraph, value)
        else:
            paragraph.add_run(text(value))
        if container is not self.doc:
            paragraph.paragraph_format.space_after = Pt(3)
            paragraph.paragraph_format.line_spacing = 1
            paragraph.paragraph_format.left_indent = Cm(0)
            paragraph.paragraph_format.first_line_indent = Cm(0)
            paragraph.paragraph_format.keep_with_next = False
            wrap = OxmlElement("w:wordWrap")
            wrap.set(qn("w:val"), "0")
            paragraph._p.get_or_add_pPr().append(wrap)
        return paragraph

    def value(self, container, value):
        """Render structured values as Word elements, never serialized JSON cells."""
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        if isinstance(value, LiteralText):
            excerpt = value.value
            if excerpt and len(excerpt) > self.config.max_excerpt_characters:
                excerpt = excerpt[:self.config.max_excerpt_characters] + "\n[Fragmento abreviado; completo en el JSON canónico.]"
            self.write(container, excerpt, linked=False)
            return
        if isinstance(value, ReferenceTarget):
            label = value.caption or self.targets[value.identifier][0]
            paragraph = self.write(container, label)
            self.bookmark(paragraph, value.identifier)
            return
        if container is not self.doc and isinstance(value, (dict, list, tuple)):
            self.cell_details(container, value)
            return
        if isinstance(value, dict):
            if not value:
                self.write(container, "Sin información publicada.")
                return
            self.table(("Elemento", "Detalle"), ((field_label(key), item) for key, item in value.items()), container)
        elif isinstance(value, (list, tuple)):
            total = len(value)
            value = value[:self.config.max_list_items]
            if not value:
                self.write(container, "Sin registros publicados.")
            elif all(isinstance(item, dict) for item in value):
                keys = list(dict.fromkeys(key for item in value for key in item))
                if 1 <= len(keys) <= 4:
                    self.table([field_label(key) for key in keys],
                        ([item.get(key) for key in keys] for item in value), container)
                else:
                    for number, item in enumerate(value, 1):
                        self.write(container, f"Registro {number}", style="Caption")
                        self.value(container, item)
            else:
                for item in value:
                    if isinstance(item, (dict, list, tuple, ReferenceTarget)) or hasattr(item, "model_dump"):
                        self.value(container, item)
                    else:
                        self.write(container, LABELS.get(item, item) if isinstance(item, str) else item, style="List Bullet")
            if total > len(value):
                self.write(container, f"Se muestran {len(value)} de {total} elementos; detalle completo en el JSON canónico.")
        else:
            self.write(container, LABELS.get(value, value) if isinstance(value, str) else value)

    def cell_details(self, container, value, prefix="", depth=0):
        """Flat labeled paragraphs keep tables readable; never nest a table in a cell."""
        if isinstance(value, ReferenceTarget):
            self.value(container, value)
            return
        if isinstance(value, (dict, list, tuple)) and depth >= self.config.max_structure_depth:
            self.write(container, f"{prefix}: detalle técnico disponible en el JSON canónico.")
            return
        if isinstance(value, dict) and value:
            # A record reference has a real document destination, not four
            # identifier rows. The target section retains its provenance.
            if isinstance(value.get("record_id"), str) and value["record_id"] in self.targets:
                self.write(container, (prefix + ": " if prefix else "") + value["record_id"])
                return
            for key, item in list(value.items())[:self.config.max_table_rows]:
                if key == "content" and (item is None or isinstance(item, str)):
                    self.write(container, field_label(key))
                    self.value(container, LiteralText(item))
                    continue
                if key == "invocation_id" and isinstance(item, str) and item in self.execution_targets:
                    item = self.execution_targets[item]
                self.cell_details(container, item, f"{prefix} · {field_label(key)}" if prefix else field_label(key), depth + 1)
            if len(value) > self.config.max_table_rows:
                self.write(container, f"{prefix}: {len(value)} campos; resto en el JSON canónico.")
        elif isinstance(value, (list, tuple)) and value:
            for item in value[:self.config.max_list_items]:
                self.cell_details(container, item, prefix, depth + 1)
            if len(value) > self.config.max_list_items:
                self.write(container, f"{prefix}: {len(value)} elementos; se muestran {self.config.max_list_items}. Resto en el JSON canónico.")
        else:
            formatted = LABELS.get(value, value) if isinstance(value, str) else value
            if isinstance(value, (dict, list, tuple)):
                formatted = "Sin registros publicados."
            self.write(container, f"{prefix}: {text(formatted)}" if prefix else formatted)

    def table(self, headers, rows, container=None):
        container = container if container is not None else self.doc
        rows = list(rows)
        if not rows:
            self.write(container, "Sin registros publicados.")
            return
        total_rows = len(rows)
        rows = rows[:self.config.max_table_rows]
        if total_rows > len(rows):
            self.write(container, f"Se muestran {len(rows)} de {total_rows} registros; detalle completo en el JSON canónico.")
        if container is self.doc and len(rows) > 12:
            self.paragraph(f"Detalle extenso: {len(rows)} registros. Puede contraer o expandir el encabezado siguiente en Word compatible.")
            self.heading(f"Detalle de tabla — {headers[0]} ({len(rows)} registros)", 4, collapsed=True)
        table = container.add_table(rows=1, cols=len(headers))
        if container is not self.doc and len(container.paragraphs) > 1 and not container.paragraphs[0].text:
            empty = container.paragraphs[0]._p
            empty.getparent().remove(empty)
        table.style = "Light Shading Accent 1"
        table.autofit = False
        available = self.doc.sections[0].page_width - self.doc.sections[0].left_margin - self.doc.sections[0].right_margin
        proportions = {2: (0.27, 0.73), 3: (0.25, 0.35, 0.40), 4: (0.31, 0.23, 0.23, 0.23)}.get(
            len(headers), tuple(1 / len(headers) for _ in headers))
        for column, proportion in zip(table.columns, proportions, strict=True):
            column.width = int(available * proportion)
        width = table._tbl.tblPr.find(qn("w:tblW"))
        width.set(qn("w:type"), "dxa")
        width.set(qn("w:w"), str(round(available / 635)))
        table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        for cell, header in zip(table.rows[0].cells, headers, strict=True):
            cell.text = text(header)
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), "17365D")
            cell._tc.get_or_add_tcPr().append(shade)
            for run in cell.paragraphs[0].runs:
                run.font.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)
            cell.paragraphs[0].paragraph_format.keep_with_next = True
        rendered_rows = []
        for row in rows:
            cells = table.add_row().cells
            rendered_rows.append(cells)
            for cell, value in zip(cells, row, strict=True):
                cell.text = ""
                self.value(cell, value)
        for cells in [table.rows[0].cells, *rendered_rows]:
            for cell, proportion in zip(cells, proportions, strict=True):
                cell.width = int(available * proportion)
                align = OxmlElement("w:vAlign")
                align.set(qn("w:val"), "top")
                cell._tc.get_or_add_tcPr().append(align)
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.space_after = Pt(3)
                    for run in paragraph.runs:
                        run.font.size = Pt(9)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def fields(self, rows):
        self.table(("Elemento", "Detalle"), [(key, value) for key, value in rows if value not in (None, "", [], {})])

    def listing(self, values):
        if not values:
            self.paragraph("Sin información publicada.")
            return
        self.value(self.doc, values)

    def statements(self, values):
        if not values:
            self.paragraph("Sin resultados publicados.")
        for value in values[:self.config.max_list_items]:
            self.paragraph(value.text)
            if value.source_refs:
                refs = list(dict.fromkeys(item.record_id for item in value.source_refs))
                self.paragraph("Fuentes: " + "; ".join(refs[:self.config.max_list_items])
                    + (f"; {len(refs) - self.config.max_list_items} referencias adicionales en el JSON canónico." if len(refs) > self.config.max_list_items else ""))
        if len(values) > self.config.max_list_items:
            self.paragraph(f"Se muestran {self.config.max_list_items} de {len(values)} resultados; el JSON canónico conserva todos.")

    def statistics(self, counts):
        self.paragraph(f"Total: {counts.total}. Base de conteo: registros originales de hallazgos del blackboard.")
        self.table(("Severidad", "Verificados", "Inconclusos", "Descartados"), (
            (LABELS.get(severity, severity), values.get("verified", 0), values.get("inconclusive", 0), values.get("discarded", 0))
            for severity, values in counts.by_severity_and_verification.items()))
        self.table(("Atributo", "Hallazgos"), ((LABELS.get(key, key), count) for key, count in counts.by_attribute.items()))
        self.table(("Componente", "Hallazgos verificados"), sorted(counts.verified_by_component.items()))

    def build(self):
        report = self.report
        severity_order = {key: number for number, key in enumerate(("critical", "high", "medium", "low", "info"))}
        ordered_findings = sorted(report.quality_results.findings, key=lambda finding: (
            finding.lifecycle != "current", {"verified": 0, "inconclusive": 1, "discarded": 2}[finding.verification_status],
            severity_order.get(finding.severity, 5), finding.id))
        priority_order = {key: number for number, key in enumerate(("urgent", "high", "medium", "low", "undetermined"))}
        ordered_risks = sorted(report.consolidated_risks.risks, key=lambda item: (priority_order[item.priority], item.id))
        ordered_actions = sorted(report.recommendations_and_improvement_plan, key=lambda item: (priority_order[item.priority], item.id))
        detailed_findings, represented_security_groups = [], set()
        for finding in ordered_findings:
            group = (finding.criterion.id, finding.severity, finding.verification_status, finding.lifecycle)
            if finding.quality_attribute == "security" and finding.verification_status != "verified":
                if group in represented_security_groups:
                    continue
                represented_security_groups.add(group)
            detailed_findings.append(finding)
            if len(detailed_findings) == self.config.max_detailed_findings:
                break
        identity = report.identification
        self.doc.add_heading(text(identity.title), 0)
        self.paragraph("Las referencias azules enlazan con su sección en este documento. "
            "La información emergente del enlace conserva el identificador de origen.")
        self.paragraph("Versión de lectura: prioriza conclusiones, hallazgos y acciones. "
            "Los inventarios extensos se resumen y las selecciones se indican expresamente. "
            "El JSON canónico asociado conserva todos los hallazgos, evidencias, configuraciones, "
            "diagnósticos y registros originales; la selección editorial no cambia sus estados ni sus conteos.")
        self.paragraph("Los bloques extensos tienen encabezados plegables: use la flecha junto al título o "
            "Expandir/contraer desde su menú contextual en Word de escritorio compatible. "
            "Otros visores pueden mostrar todo el contenido expandido.")
        self.heading("1. Portada e identificación de la auditoría")
        self.fields([("Auditoría", identity.audit_id), ("Proyecto", identity.project_name),
            ("Repositorio", identity.repository_url or identity.repository_location),
            ("Fecha de ejecución", identity.executed_at.isoformat() if identity.executed_at else None),
            ("Fecha de emisión", identity.issued_at.isoformat()), ("Estado", LABELS[identity.status]),
            ("Versión del esquema", report.schema_version), ("Presentación documental", DOCX_RENDERER_VERSION), ("Idioma", report.language),
            ("Digest de registros de origen", identity.source_digest)])
        self.table(("Repositorio", "Commit", "Snapshot"),
            ((item.repository_id, item.commit, item.snapshot_hash) for item in identity.revisions))
        self.doc.add_page_break()

        self.heading("2. Resumen ejecutivo")
        summary = report.executive_summary
        self.statements(summary.objective)
        self.statements(summary.principal_results)
        self.table(("Atributo", "Estado", "Conclusión"), ((item.title, LABELS[item.status], item.conclusion)
            for item in report.quality_results.attributes))
        self.statistics(summary.findings)
        self.fields([("Principales riesgos", summary.principal_risk_ids), ("Conclusión", summary.conclusion)])

        self.heading("3. Objetivos y alcance de la auditoría")
        scope = report.objectives_and_scope
        self.heading("Objetivo general", 2)
        self.statements(scope.general_objectives)
        self.heading("Objetivos específicos", 2)
        self.statements(scope.specific_objectives)
        self.fields([("Atributos y subcaracterísticas", scope.attributes_and_subcharacteristics),
            ("Componentes incluidos", scope.included_components), ("Archivos inspeccionados", scope.inspected_files),
            ("Objetivos de alcance declarados", scope.declared_targets), ("Exclusiones", scope.exclusions),
            ("Restricciones y limitaciones", scope.limitations)])

        self.heading("4. Metodología y criterios de evaluación")
        methodology = report.methodology_and_criteria
        self.paragraph(methodology.quality_model)
        self.table(("Criterio", "Descripción", "Origen y procedencia"),
            ((item.id, item.description, f"{item.origin}: {item.provenance}") for item in methodology.applied_criteria))
        self.fields([("Análisis estático", methodology.static_analysis), ("Herramientas", methodology.tools),
            ("Validación de hallazgos", methodology.finding_validation),
            ("Criterios de severidad", methodology.severity_criteria), ("Limitaciones", methodology.limitations)])
        self.heading("Análisis dinámico registrado", 2)
        self.statements(methodology.dynamic_analysis)

        self.heading("5. Descripción general del software evaluado")
        software = report.software_description
        self.statements([software.description] if software.description else [])
        self.fields([("Lenguajes", software.languages),
            ("Estructura del repositorio", software.repository_structure), ("Módulos", software.modules),
            ("Limitaciones", software.limitations),
            ("Fuentes", [item.model_dump(mode="json") for item in software.source_refs])])
        self.heading("Tecnologías detectadas", 2)
        self.table(("Tecnología", "Tipo", "Versión declarada", "Proyecto"), ((item.get("name"), item.get("kind"),
            item.get("version_constraint"), item.get("project_id")) for item in software.technologies))
        self.heading("Dependencias registradas", 2)
        self.table(("Dependencia", "Ecosistema / alcance", "Versión declarada", "Proyecto"), ((item.get("name"),
            " / ".join(str(item[key]) for key in ("ecosystem", "scope") if item.get(key)),
            item.get("version_constraint"), item.get("project_id")) for item in software.dependencies))
        self.heading("Entorno e infraestructura detectados", 2)
        self.table(("Componente", "Tipo", "Imagen / puertos", "Proyecto"), ((item.get("name"), item.get("kind"),
            [item.get("image"), *item.get("ports", [])], item.get("project_id")) for item in software.runtime_environment))
        self.heading("Arquitectura respaldada por evidencia", 2)
        self.statements(software.architecture)

        self.heading("6. Resultados de la evaluación de calidad")
        for number, attribute in enumerate(report.quality_results.attributes, 1):
            self.heading(f"6.{number}. {attribute.title}", 2)
            self.paragraph("Estado: " + LABELS[attribute.status])
            self.statements(attribute.summary)
            for subnumber, sub in enumerate(attribute.subcharacteristics, 1):
                self.heading(f"6.{number}.{subnumber}. {sub.title}", 3)
                self.fields([("Estado", LABELS[sub.status]), ("Temas de referencia (la cobertura se detalla por compromiso)", sub.evaluation_topics),
                    ("Hallazgos", sub.finding_ids), ("Limitaciones", (
                        f"Se conservan {len(sub.limitations)} limitaciones originales en los anexos de ejecución y trazabilidad."
                        if sub.limitations else "Sin limitaciones adicionales publicadas."))])
                self.statements(sub.assessments)
                self.paragraph(sub.conclusion)
            self.heading(f"Conclusión general de {attribute.title.lower()}", 3)
            self.paragraph(attribute.conclusion)
        self.heading("Inventario resumido de hallazgos", 2)
        self.paragraph("Los hallazgos inconclusos o descartados no representan defectos confirmados.")
        groups = defaultdict(list)
        for finding in report.quality_results.findings:
            groups[(finding.quality_attribute, finding.criterion.id, finding.severity,
                finding.verification_status, finding.lifecycle)].append(finding)
        self.table(("Criterio / atributo", "Severidad / verificación / vigencia", "Registros", "Ejemplos"), (
            (f"{items[0].criterion.description} · {LABELS.get(key[0], key[0])}",
                f"{LABELS.get(key[2], key[2]) or 'No determinada'} / {LABELS[key[3]]} / {key[4]}", len(items),
                [item.id for item in items[:3]]) for key, items in groups.items()))
        self.heading("Hallazgos prioritarios", 2)
        self.paragraph(f"Se desarrollan {len(detailed_findings)} de {len(ordered_findings)} hallazgos. "
            "Se priorizan registros vigentes, verificados y de mayor severidad; después los candidatos inconclusos. "
            "Los candidatos de seguridad repetidos por criterio, severidad, estado y vigencia se ilustran con un representante. "
            "Los demás registros permanecen en el JSON canónico, incluidos los históricos y descartados.")
        for finding in detailed_findings:
            self.heading(f"{self.targets[finding.id][0]} — {finding.title}", 3, target=finding.id)
            self.fields([("Atributo / subcaracterística", f"{finding.quality_attribute} / {finding.subcharacteristic}"),
                ("Severidad", LABELS.get(finding.severity, "No determinada")),
                ("Estado de verificación", LABELS[finding.verification_status]),
                ("Vigencia", finding.lifecycle),
                ("Tipo / clasificación", f"{finding.kind} / {finding.classification}"), ("Descripción", finding.description),
                ("Criterio", finding.criterion.model_dump(mode="json")), ("Justificación", finding.justification),
                ("Componentes", finding.components), ("Evidencias", finding.evidence_ids), ("Impacto", finding.impact),
                ("Recomendación", finding.recommendation), ("Revisión", finding.verification_rationale),
                ("Problemas de validación", finding.validation_issues),
                ("Contexto y condiciones de interpretación", {key: value for key, value in {
                    "assessed_context": finding.assessed_context, "sharing_boundary": finding.sharing_boundary,
                    "conditions": finding.conditions, "assumptions": finding.assumptions,
                    "unknowns": finding.unknowns, "limitations": finding.limitations}.items() if value}),
                ])
            security = finding.technical_details.get("security_finding", {})
            if isinstance(security, dict) and security:
                self.fields([("Ubicación del candidato", f"{security.get('file_path', '')}:{security.get('line_number', '')}"),
                    ("Regla del escáner", security.get("rule_id"))])
                self.paragraph("Detección heurística: la severidad del escáner no confirma explotabilidad. "
                    "La propuesta de parche se conserva en el JSON canónico y no acredita una corrección validada.")

        self.heading("7. Análisis consolidado de riesgos")
        risk = report.consolidated_risks
        self.paragraph(f"Se registran {len(risk.risks)} riesgos derivados de hallazgos vigentes verificados. "
            "La distribución completa de hallazgos por severidad y verificación figura en el resumen ejecutivo; "
            "los candidatos inconclusos no se contabilizan como defectos confirmados.")
        self.paragraph(risk.prioritization_method)
        self.table(("Riesgo / hallazgos", "Componentes", "Impacto", "Prioridad"),
            (([ReferenceTarget(item.id), *item.finding_ids], ", ".join(item.components), item.description,
                  LABELS.get(item.priority, item.priority)) for item in ordered_risks))
        for item in ordered_risks[:self.config.max_table_rows]:
            self.fields([("Riesgo", ReferenceTarget(item.id)), ("Tipo", item.risk_type),
                ("Contexto evaluado", item.assessed_context), ("Condiciones", item.conditions),
                ("Supuestos", item.assumptions), ("Desconocidos", item.unknowns), ("Limitaciones", item.limitations)])
        self.heading("Relaciones entre hallazgos", 2)
        self.table(("Relación / estado", "Hallazgos", "Justificación", "Fuentes"),
            ((f"{item.kind} / {item.status}", item.finding_ids, item.rationale,
                [ref.model_dump(mode="json") for ref in item.source_refs]) for item in risk.relationships))

        self.heading("8. Conclusiones generales de la auditoría")
        conclusions = report.general_conclusions
        self.statements(conclusions.by_attribute)
        self.heading("Fortalezas", 2)
        self.statements(conclusions.strengths)
        self.heading("Debilidades", 2)
        self.statements(conclusions.weaknesses)
        self.fields([("Aspectos críticos", conclusions.critical_finding_ids), ("Limitaciones", conclusions.limitations)])
        self.paragraph(conclusions.general_conclusion)

        self.heading("9. Recomendaciones y plan de mejora")
        if not report.recommendations_and_improvement_plan:
            self.paragraph("No constan recomendaciones asociadas a hallazgos vigentes verificados.")
        if len(report.recommendations_and_improvement_plan) > self.config.max_table_rows:
            self.paragraph(f"Se desarrollan {self.config.max_table_rows} de {len(report.recommendations_and_improvement_plan)} acciones; "
                "el plan completo permanece en el JSON canónico.")
        for item in ordered_actions[:self.config.max_table_rows]:
            self.heading(self.targets[item.id][0], 2, target=item.id)
            self.fields([("Hallazgos", item.finding_ids), ("Acción", item.action),
                ("Tipo de acción", item.action_type), ("Contexto evaluado", item.assessed_context),
                ("Frontera de compartición", item.sharing_boundary), ("Condiciones", item.conditions),
                ("Supuestos", item.assumptions), ("Desconocidos", item.unknowns), ("Limitaciones", item.limitations),
                ("Justificación técnica", item.technical_justification), ("Prioridad", LABELS[item.priority]),
                ("Beneficio esperado", item.expected_benefit),
                ("Criterio propuesto de verificación", item.proposed_verification_criterion)])

        self.heading("10. Anexos y trazabilidad")
        annexes = report.annexes_and_traceability
        if annexes.generation is not None:
            generation = annexes.generation
            self.heading("Registro de construcción del informe", 2)
            self.fields([("Generación", generation.generation_id), ("Versión del generador", generation.generator_version),
                ("Digest de entrada", generation.source_digest), ("Validación documental", generation.validation_status),
                ("Comprobaciones", generation.validation_checks), ("Incidencias", generation.issues),
                ("Evaluaciones vigentes", generation.effective_assessment_ids),
                ("Evaluaciones históricas", generation.historical_assessment_ids)])
            self.paragraph("El JSON canónico conserva el snapshot de entrada completo para reconstruir el informe por separado.")
            self.paragraph(f"{len(generation.decisions)} decisiones documentales conservadas en el JSON canónico.")
        self.heading(f"Cobertura de compromisos ({len(annexes.coverage_commitments)} registros)", 2, collapsed=True)
        self.table(("Agente / hipótesis", "Sujetos / evidencias", "Estado / vigencia", "Pregunta / limitaciones"),
            ((f"{c.agent_id} / {c.hypothesis_id}", [*c.subject_ids, *c.evidence_ids], f"{c.status} / {c.lifecycle}",
                [c.question, *c.validation_issues]) for c in annexes.coverage_commitments))
        self.heading("Diagnóstico de la ejecución", 2, collapsed=True)
        self.paragraph("Las incidencias de ejecución limitan la auditoría; no son defectos confirmados del software evaluado.")
        issue_groups = defaultdict(list)
        for item in annexes.execution_issues:
            issue_groups[(item.agent_id, item.termination_reason, item.explanation)].append(item)
        self.table(("Agente / causa", "Efecto sobre la auditoría", "Ejecuciones / diagnósticos"), (
            (f"{key[0]} / {key[1] or 'Sin motivo publicado'}", key[2],
                (f"{len(items)} ejecuciones; {sum(len(item.diagnostics) for item in items)} diagnósticos. "
                "Registro completo en el JSON canónico.")) for key, items in issue_groups.items()))
        self.paragraph("Los intentos repetidos y las trazas del proveedor no se reproducen individualmente. "
            "Una cobertura incompleta impide concluir sobre el código no inspeccionado.")
        self.fields([("Agentes participantes", annexes.participants), ("Herramientas", annexes.tools),
            ("Registros conservados", (f"{len(annexes.evidence_inventory)} evidencias; {len(annexes.assessments)} evaluaciones; "
                f"{len(annexes.tool_call_ids)} IDs de llamadas de herramientas.")),
            ("Referencias sin resolver", annexes.unresolved_references)])
        self.heading("Evaluaciones de origen", 2)
        for item in annexes.assessments[:self.config.max_list_items]:
            self.heading(f"{self.targets[item.record_id][0]} — {item.agent_id}", 3, target=item.record_id)
            self.fields([("Agente", item.agent_id), ("Ejecución", self.execution_targets.get(item.invocation_id, item.invocation_id)),
                ("Registro de origen", item.record_id)])
        self.heading(f"Inventario de evidencias ({len(annexes.evidence_inventory)} registros)", 2, collapsed=True)
        relevant_ids = {identifier for finding in detailed_findings for identifier in finding.evidence_ids}
        evidence_selection = sorted(annexes.evidence_inventory, key=lambda item: (
            item.id not in relevant_ids, item.kind != "source", item.id))[:self.config.max_evidence_excerpts]
        self.paragraph(f"Se muestran {len(evidence_selection)} de {len(annexes.evidence_inventory)} evidencias, "
            "priorizando las citadas por los hallazgos desarrollados. Los fragmentos pueden estar abreviados; "
            "todos los registros completos están en el JSON canónico.")
        for item in evidence_selection:
            self.heading(f"{self.targets[item.id][0]} — {item.source}", 3, target=item.id, collapsed=True)
            self.fields([("Archivo o fuente", item.source), ("Líneas", f"{item.start_line}–{item.end_line}" if item.start_line else None),
                ("Contenido registrado", LiteralText(item.content)), ("Verificación del commit", item.commit_verification),
                ("Símbolos", item.symbol_ids), ("Registro de origen", item.id)])
        self.heading("Registros de ejecución y validación", 2, collapsed=True)
        self.table(("Agente / invocación", "Estado / terminación", "Recursos"),
            ((f"{item.agent_id}\n{self.execution_targets[item.invocation_id]}", f"{LABELS.get(item.status, item.status)} / {item.termination_reason or 'No consta'}",
                item.consumption) for item in annexes.executions))
        for item in annexes.executions[:self.config.max_list_items]:
            target = self.execution_targets[item.invocation_id]
            self.heading(f"{self.targets[target][0]} — {item.agent_id}", 3, target=target, collapsed=True)
            self.fields([("Evaluaciones", item.assessment_ids),
                ("Limitaciones del análisis", [value for value in item.limitations if not any(marker in value for marker in
                    ("security_source_read:", "security_remediation:", "provider_request:", "response_schema"))]),
                ("Detalle técnico", (f"{len(item.limitations)} limitaciones y {len(item.unresolved_results)} resultados pendientes; "
                    "el contenido original de ejecución y validación se conserva en el JSON canónico."))])
        self.heading("Catálogo de referencias legibles", 2, collapsed=True)
        self.paragraph("Las identidades originales se conservan en la información emergente de los enlaces y en el JSON canónico. "
            "Un nombre no publicado indica que el análisis no aporta una identidad inequívoca.")
        shown_entities = [identifier for identifier in self.entity_targets if identifier in self.used_entity_targets]
        if len(shown_entities) > self.config.max_table_rows:
            self.paragraph(f"Se muestran {self.config.max_table_rows} de {len(shown_entities)} referencias legibles; "
                "el catálogo completo se conserva en el JSON canónico.")
        for identifier in shown_entities[:self.config.max_table_rows]:
            self.value(self.doc, ReferenceTarget(identifier))
        self.heading("Referencias al registro completo", 2)
        destination = self.write(self.doc, "Los enlaces a registros no desarrollados en esta versión remiten a este índice. "
            "Consulte su ID de origen en la información emergente y localícelo en el JSON canónico asociado. "
            "No se han eliminado registros del análisis.")
        for identifier in self.targets:
            if identifier not in self.bookmarks:
                self.bookmark(destination, identifier)
        buffer = BytesIO()
        self.doc.save(buffer)
        return buffer.getvalue()


def render_audit_report_docx(report: SoftwareAuditReport, *, config: ReportPresentationConfig | None = None) -> bytes:
    """Same validated JSON produces identical bytes, including DOCX ZIP metadata."""
    report = SoftwareAuditReport.model_validate(report.model_dump(mode="json"))
    raw = ReportDocument(report, config).build()
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(output, "w", compression=ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            target.writestr(info, source.read(name))
    return output.getvalue()
