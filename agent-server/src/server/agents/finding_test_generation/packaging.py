"""Build the portable Verification Suite ZIP (`.tallercito/` layout).

Deterministic and offline: no LLM, no network access, no dependency on the
audited repository's own build. The ZIP roots exactly one folder,
``.tallercito/``, designed to be extracted at the repository root.
"""

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from server.runtimes.verification.zip_pack import (
    SUITE_ROOT_NAME,
    TEMPLATES_DIR,
    copy_templates,
    stage_suite_root,
    try_uv_lock,
    write_suite_zip,
)

from .schemas import (
    AuditDocument,
    ManifestVerification,
    ValidationRecord,
    VerificationSpec,
    VerificationSuiteManifest,
)
from .test_templates import render_helper, render_test_file

GENERATOR_VERSION = "prototype-0.1"

__all__ = ["SUITE_ROOT_NAME", "TEMPLATES_DIR", "build_suite"]


def _documentary_digest(document: AuditDocument) -> list[dict]:
    digest: list[dict] = []
    for finding in document.findings:
        for reference in finding.technical_details.documentary_references:
            digest.append({
                "finding_id": finding.id,
                "document_claim_id": reference.document_claim_id,
                "constraint": reference.constraint,
                "status": reference.status,
                "sources": sorted(set(reference.section_paths.values())),
                "lines": {item.get("path", "?"): [item.get("start_line"), item.get("end_line")]
                          for item in getattr(reference, "quotes", [])},
                "commit": reference.commit,
            })
    return digest


_STRATEGY_LABEL = {"static_ast": "Estática sobre AST", "dynamic_mock": "Dinámica con mocks", "hybrid": "Híbrida (dinámica + contrato)"}
_OUTCOME_TABLE = [
    ("VIOLATION_PRESENT", "La condición denunciada persiste en el ámbito comprobado. Acción: corregir y volver a ejecutar la suite."),
    ("EXECUTION_ERROR", "El entorno no pudo certificar esta comprobación (p. ej., el código auditado no importa o no parsea). Revise `results/report.json`."),
    ("NOT_VERIFIABLE", "No hay una prueba ejecutable para esta obligación con los datos disponibles."),
    ("INCONCLUSIVE", "La prueba no distinguió entre presencia y ausencia de la condición; un pase aislado no prueba una corrección."),
]


def _short(value: str, length: int = 10) -> str:
    return value if len(value) <= length else value[:length] + "…"


def _rule_param_cell(params: dict[str, object]) -> str:
    if not params:
        return ""
    rendered = json.dumps(params, ensure_ascii=False, default=str)
    return f" · params `{_cell(rendered)}`" if len(rendered) <= 400 else f" · params `{_cell(rendered[:400])}…`"


def _blockquote(text: str) -> list[str]:
    return [f"> {line}".rstrip() for line in text.splitlines()]


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _finding_kind_label(kind: str) -> str:
    return {"violation": "Violación", "design_observation": "Observación de diseño"}.get(kind, kind or "hallazgo")


def _spec_section(document: AuditDocument, spec: VerificationSpec, index: int) -> list[str]:
    finding = document.findings[index - 1]
    header = (
        f"**Severidad `{finding.severity}`** · {_finding_kind_label(finding.kind)} · "
        f"Clasificación: `{finding.classification}` · Estado original: `{finding.verification_status}`"
    )
    lines = [
        f'<a id="hallazgo-{index}"></a>',
        f"## Hallazgo {index} · {spec.title}",
        "",
        header,
        "",
        "### Qué dice el hallazgo",
        "",
    ]
    lines += _blockquote(finding.justification)
    lines.append("")
    lines.append(f"**Impacto:** {finding.impact}")
    lines.append("")
    lines.append(f"**Recomendación original:** {finding.recommendation}")
    lines.append("")
    if finding.validation_issues:
        lines.append(f"**Issues de origen:** `{', '.join(finding.validation_issues)}`")
        lines.append("")

    if finding.technical_details.documentary_references:
        lines.append("### Documentación aplicable")
        lines.append("")
        for reference in finding.technical_details.documentary_references:
            lines.append(f"**`{reference.document_claim_id}`** — {reference.constraint or 'n/a'} · estado `{reference.status}` · commit `{reference.commit or 'n/d'}`")
            lines.append("")
            lines.append(f"*{reference.statement}*")
            for quote in reference.quotes:
                path = quote.get("path", "?")
                lines.append("")
                lines += _blockquote(quote.get("quote", "").rstrip("\n"))
                lines.append("")
                lines.append(f"— `{path}:{quote.get('start_line')}`")
            lines.append("")

    lines += [
        "### Verificación generada",
        "",
        "| Campo | Detalle |",
        "|---|---|",
        f"| Verificación | `{spec.verification_id}` |",
        f"| Estrategia | {_STRATEGY_LABEL.get(spec.strategy, spec.strategy)} |",
        f"| Regla | `{spec.rule_kind}`{_rule_param_cell(spec.rule_params)} |",
        f"| Comprueba que | {_cell(spec.property)} |",
        f"| Ámbito analizado | `{_cell(spec.source_scope)}` |",
        f"| Ámbito del escenario | {_cell(spec.test_scenario_scope)} |",
        f"| Falla si | {_cell(spec.violation_oracle)} |",
        f"| Pasa si | {_cell(spec.fixed_oracle)} |",
        f"| Prueba | `{spec.test_path}::{spec.test_name}` |",
        "",
        "### Qué demuestra esta prueba",
        "",
        "- Si falla, la condición denunciada **persiste** en el ámbito comprobado.",
        "- Si pasa, la condición **no se observó** en ese ámbito. No certifica el resto de la arquitectura.",
        "- El `verification_status` original del hallazgo no cambia por ejecutar esta prueba.",
        "",
        "### Qué no demuestra",
        "",
    ]
    lines += [f"- {item}" for item in spec.limits]
    lines += [
        "",
        "### Cómo interpretar su resultado",
        "",
        "| Resultado | Significado para este hallazgo |",
        "|---|---|",
    ]
    lines += [f"| `{status}` | {detail} |" for status, detail in _OUTCOME_TABLE]
    lines.append("")
    return lines


def _report_markdown(document: AuditDocument, specs: list[VerificationSpec], manifest: VerificationSuiteManifest) -> str:
    specs_by_finding: dict[str, list[VerificationSpec]] = {}
    for spec in specs:
        specs_by_finding.setdefault(spec.finding_id, []).append(spec)
    kinds = {"violation": 0, "design_observation": 0}
    for finding in document.findings:
        kinds[finding.kind] = kinds.get(finding.kind, 0) + 1
    kind_parts = []
    if kinds.get("violation"):
        kind_parts.append(f"{kinds['violation']} violación" + ("es" if kinds["violation"] > 1 else ""))
    if kinds.get("design_observation"):
        kind_parts.append(f"{kinds['design_observation']} observación" + ("es" if kinds["design_observation"] > 1 else ""))
    kind_summary = ", ".join(kind_parts)
    generated = len(specs)
    important_note = (
        "> **Importante:** generar o ejecutar esta suite no revisa ni modifica los hallazgos originales. "
        "Cada uno conserva su `verification_status`. Una prueba solo demuestra su propiedad en el ámbito indicado."
    )

    lines = [
        f"# Verification report — auditoría {document.audit_id}",
        "",
        "| | |",
        "|---|---|",
        f"| **Auditoría** | {document.audit_id} |",
        f"| **Commit auditado** | `{document.commit_hash}` |",
        f"| **Generada** | {datetime.now(UTC).isoformat(timespec='seconds')} |",
        f"| **Suite** | `{manifest.suite_id}` · generador `{GENERATOR_VERSION}` |",
        f"| **Hallazgos** | {len(document.findings)} ({kind_summary}) |",
        f"| **Verificaciones generadas** | {generated} |",
        "",
        important_note,
        "",        "## Resumen",
        "",
        "| # | Hallazgo | Sev. | Tipo | Verificación | Estrategia | Estado original |",
        "|---|---|---|---|---|---|---|",
    ]
    for position, finding in enumerate(document.findings, start=1):
        related = specs_by_finding.get(finding.id, [])
        spec = related[0] if related else None
        verification = spec.verification_id if spec else "—"
        strategy = _STRATEGY_LABEL.get(spec.strategy, spec.strategy) if spec else "no verificable"
        lines.append(
            f"| {position} | [{_cell(_short(finding.title, 60))}](#hallazgo-{position}) `{_short(finding.id, 8)}` | {finding.severity} | "
            f"{_finding_kind_label(finding.kind)} | {verification} | {strategy} | `{finding.verification_status}` |"
        )
    lines += [
        "",
        "## Índice",
        "",
        *[f"{position}. [{finding.title}](#hallazgo-{position}) — `{_short(finding.id, 8)}`" for position, finding in enumerate(document.findings, start=1)],
        "",
    ]
    for number, finding in enumerate(document.findings, start=1):
        related = specs_by_finding.get(finding.id, [])
        if not related:
            lines += [
                f'<a id="hallazgo-{number}"></a>',
                f"## Hallazgo {number} · {finding.title}",
                "",
                f"**Severidad `{finding.severity}`** · {_finding_kind_label(finding.kind)} · Estado original: `{finding.verification_status}`",
                "",
                "### Qué dice el hallazgo",
                "",
                *_blockquote(finding.justification),
                "",
                f"**Impacto:** {finding.impact}",
                "",
                f"**Recomendación original:** {finding.recommendation}",
                "",
                "**Sin verificación determinista aplicable** — `NOT_VERIFIABLE` hasta disponer de generación con LLM (hito posterior).",
                "",
            ]
            continue
        for spec in related:
            lines += _spec_section(document, spec, number)

    if manifest.limitations:
        lines += ["## Limitaciones globales de esta generación", "", *[f"- {item}" for item in dict.fromkeys(manifest.limitations)], ""]

    lines += [
        "## Cómo interpretar el conjunto",
        "",
        "| Código de salida | Significado |",
        "|---|---|",
        "| `0` | Ninguna violación observada en las pruebas ejecutadas (no implica conformidad total). |",
        "| `1` | Al menos una violación detectada; ver `results/report.json` para el detalle. |",
        "| `2` | Error de entorno/ejecución o ninguna verificación pudo certificarse. |",
        "",
        "## Regenerar esta suite",
        "",
        "```bash",
        "uv run python -m server.agents.finding_test_generation.cli generate \\",
        "  --findings fixtures/audit_140/findings.json \\",
        "  --repo appdata/workspace/1454248654-redsquirrelx-urban-mesh \\",
        "  --output ./artifacts/audit-140",
        "```",
        "",
        "Los resultados de la ejecución local se escriben en `.tallercito/results/` y nunca modifican el código fuente.",
        "",
    ]
    return "\n".join(lines)


def build_suite(
    document: AuditDocument,
    specs: list[VerificationSpec],
    validation_records: list[ValidationRecord],
    limitations: list[str],
    output_zip: Path,
    test_contents: dict[str, str] | None = None,
    generation_sources: dict[str, str] | None = None,
) -> tuple[VerificationSuiteManifest, Path]:
    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    suite_id = f"audit-{document.audit_id}-{uuid.uuid4().hex[:8]}"

    stage, root = stage_suite_root()
    try:
        # Portable launcher scripts and runner come from maintained templates.
        copy_templates(root, readme_replacements={
            "__AUDIT_ID__": str(document.audit_id),
            "__SOURCE_COMMIT__": document.commit_hash,
        })

        # Resolve the suite lock at packaging time when possible; never ship a fake one.
        if any(spec.language != "python" for spec in specs) and not any(spec.language == "python" for spec in specs):
            lock_limitation = None
        else:
            lock_limitation = try_uv_lock(root)
        if lock_limitation:
            limitations = [*limitations, lock_limitation]

        test_files = []
        for spec in specs:
            content = (test_contents or {}).get(spec.verification_id)
            test_files.append((spec.test_path, content) if content is not None else render_test_file(spec))
        has_python = any(spec.language == "python" for spec in specs)
        has_node = any(spec.language != "python" for spec in specs)
        helpers = [render_helper("python") for _ in [None] if has_python] + [render_helper("typescript") for _ in [None] if has_node]
        for name, content in (*helpers, *test_files):
            (root / name).write_text(content, encoding="utf-8")

        records_by_id = {record.verification_id: record for record in validation_records}
        sources = dict(generation_sources or {})
        verifications = [
            ManifestVerification(
                finding_id=spec.finding_id,
                verification_id=spec.verification_id,
                test_path=spec.test_path,
                test_name=spec.test_name,
                strategy=spec.strategy,
                covered_property=spec.property,
                target_components=spec.target_components,
                document_claim_ids=spec.rule_source.document_claim_ids,
                rule_id=spec.rule_kind,
                rule_params=spec.rule_params,
                generated_by=sources.get(spec.verification_id),
                generation_status=records_by_id.get(spec.verification_id, ValidationRecord(verification_id=spec.verification_id, status="generated")).status,
                coverage_limitations=spec.limits,
                language=spec.language,
                framework="vitest" if spec.language != "python" else "pytest",
            )
            for spec in specs
        ]
        suite_language = ("mixed" if has_python and has_node else "python") if has_python else ("node" if has_node else "python")
        runner_language = "mixed" if has_python and has_node else suite_language

        manifest = VerificationSuiteManifest(
            audit_id=document.audit_id,
            source_commit=document.commit_hash,
            suite_id=suite_id,
            generator_version=GENERATOR_VERSION,
            documentary_references=_documentary_digest(document),
            verifications=verifications,
            limitations=limitations,
            project_language=suite_language,
            runner=runner_language,
        )
        (root / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (root / "docs" / "verification-report.md").write_text(
            _report_markdown(document, specs, manifest), encoding="utf-8")
        # results/ is written when the developer runs the suite; it is not part of the ZIP.
        write_suite_zip(stage, root, output_zip)
        return manifest, output_zip
    finally:
        shutil.rmtree(stage, ignore_errors=True)
