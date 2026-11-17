"""Build the portable Verification Suite ZIP (.tallercito/ layout).

Deterministic and offline: no LLM at packaging time. The ZIP roots exactly
one folder, ``.tallercito/``, designed to be extracted at the repository
root. The packaged manifest is runner-compatible (audit_id/source_commit/
verifications[].test_path etc.) and extends it with probe metadata:
condition, language, framework, evidence_refs and the per-verification
generation/validation states kept on separate axes.
"""

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from server.runtimes.verification.zip_pack import (
    SUITE_ROOT_NAME,
    copy_templates,
    stage_suite_root,
    try_uv_lock,
    write_suite_zip,
)

from .schemas import (
    GENERATOR_ID,
    GENERATOR_VERSION,
    PlannedVerification,
    ProbeManifest,
    ProbeManifestVerification,
    ValidationRecord,
    VerificationResult,
)

__all__ = ["SUITE_ROOT_NAME", "build_suite", "resolve_suite_id"]


def resolve_suite_id(repository_id: str) -> str:
    slug = "".join(character if character.isalnum() else "-" for character in (repository_id or "repo")).strip("-").lower() or "repo"
    return f"probe-{slug[:40]}-{uuid.uuid4().hex[:8]}"


def _short(value: str, length: int = 10) -> str:
    return value if len(value) <= length else value[:length] + "..."


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _blockquote(text: str) -> list[str]:
    return [f"> {line}".rstrip() for line in str(text).splitlines()]


def _report_markdown(document, plans: list[PlannedVerification],
                     results: list[VerificationResult],
                     records: list[ValidationRecord],
                     manifest: ProbeManifest) -> str:
    results_by_id = {item.verification_id: item for item in results}
    records_by_id = {item.verification_id: item for item in records}
    lines = [
        f"# Verification report — {document.repository_id}",
        "",
        "| | |",
        "|---|---|",
        f"| **Investigación** | `{manifest.audit_id}` |",
        f"| **Commit fuente** | `{manifest.source_commit or 'desconocido'}` |",
        f"| **Generada** | {datetime.now(UTC).isoformat(timespec='seconds')} |",
        f"| **Suite** | `{manifest.suite_id}` — generador `{GENERATOR_VERSION}` |",
        f"| **Hallazgos recibidos** | {len(document.findings)} |",
        f"| **Verificaciones generadas** | {len(plans)} |",
        "",
        ("> **Importante:** esta suite comprueba condiciones concretas de hallazgos ya identificados. "
         "No revisa ni corrige el código auditado, ni cambia el `verification_status` original de ningún hallazgo. "
         "Un pase aislado solo indica que la condición no se observó en su alcance; nunca prueba una corrección (`INCONCLUSIVE`)."),
        "",
        "## Índice",
        "",
    ]
    for position, finding in enumerate(document.findings, start=1):
        lines.append(f"{position}. [{finding.title or finding.id}](#hallazgo-{position}) — `{_short(finding.id, 16)}`")
    lines.append("")

    if not plans:
        lines += [
            "## Sin verificaciones generadas",
            "",
            ("No se recibieron hallazgos verificables en la entrada (lista vacía o sin condiciones comprobables con la evidencia disponible). "
             "Esto NO demuestra que el proyecto esté libre de defectos; únicamente que no había hallazgos que verificar."),
            "",
        ]

    plans_by_finding: dict[str, list[PlannedVerification]] = {}
    for plan in plans:
        plans_by_finding.setdefault(plan.finding_id, []).append(plan)

    for position, finding in enumerate(document.findings, start=1):
        lines += [f'<a id="hallazgo-{position}"></a>', f"## Hallazgo {position} — {finding.title}", ""]
        lines.append(f"**Severidad `{finding.severity or 'n/d'}`** — tipo `{finding.kind or 'n/d'}` — criterio `{finding.criterion_id or 'n/d'}`")
        lines.append("")
        lines += ["### Qué dice el hallazgo", ""]
        lines += _blockquote(finding.justification or finding.description or "(sin justificación)")
        lines.append("")
        if finding.modularity_impact:
            lines += [f"**Impacto:** {finding.modularity_impact}", ""]
        if finding.recommendation:
            lines += [f"**Recomendación original:** {finding.recommendation}", ""]
        if finding.evidence:
            lines += ["### Evidencia asociada", ""]
            for evidence in finding.evidence[:8]:
                loc = ""
                if evidence.start_line is not None:
                    loc = f":{evidence.start_line}-{evidence.end_line or evidence.start_line}"
                lines.append(f"- `{evidence.path}{loc}` (`{evidence.kind or 'n/d'}`, hash `{_short(evidence.content_hash, 12)}`)")
            lines.append("")
        related = plans_by_finding.get(finding.id, [])
        if not related:
            lines += ["### Verificación generada", "", "**Nada** — no se pudo planificar una verificación ejecutable para este hallazgo con la evidencia disponible (ver limitaciones).", ""]
            continue
        for plan in related:
            result = results_by_id.get(plan.verification_id)
            record = records_by_id.get(plan.verification_id)
            lines += [
                "### Verificación " + plan.verification_id,
                "",
                "| Campo | Detalle |",
                "|---|---|",
                f"| Condición | {_cell(plan.condition)} |",
                f"| Estrategia | `{plan.strategy}` |",
                f"| Comprueba que | {_cell(plan.property)} |",
                f"| Escenarios | {_cell('; '.join(plan.scenarios))} |",
                f"| Falla si | {_cell(plan.violation_oracle)} |",
                f"| Pasa si | {_cell(plan.fixed_oracle)} |",
                f"| Prueba | `{plan.test_path}::{plan.test_name}` |",
                "",
                "### Resultado observado en la validación inicial",
                "",
                f"- **Outcome (LLM + oráculo):** `{result.outcome if result else 'not_run'}`",
                f"- **Generación:** `{record.status if record else 'not_generated'}` (intentos: {record.attempts if record else 0})",
            ]
            if result and result.assertion_message:
                lines.append(f"- **Detalle del mensaje:** `{_cell(result.assertion_message[:300])}`")
            if plan.limits:
                lines += ["", "### Qué no demuestra", ""]
                lines += [f"- {item}" for item in plan.limits]
            lines.append("")

    lines += [
        "## Cómo interpretar el conjunto",
        "",
        "| Código de salida | Significado |",
        "|---|---|",
        "| `0` | Ninguna violación observada en las pruebas ejecutadas (no implica conformidad total). |",
        "| `1` | Al menos una violación detectada; ver `results/report.json`. |",
        "| `2` | Error de entorno/ejecución o ninguna verificación pudo confirmarse. |",
        "",
        "## Ejecutar sobre otro commit",
        "",
        ("Descomprima esta suite en la raíz del repositorio y ejecute `.tallercito/run.sh` (o `.tallercito\\run.bat`). "
         "La suite no invoca ningún LLM; funciona con `uv` y pytest sobre cualquier commit del mismo repositorio. "
         "Si una prueba deja de ejecutarse tras un refactor, repórtela como verificación inválida u obsoleta, "
         "no como corrección confirmada."),
        "",
        "## Regenerar la suite",
        "",
        "```bash",
        "uv run python -m server.agents.testability_probe.cli generate \\",
        "  --findings <artifacts/test-isolation-*.json> \\",
        "  --repo <ruta/al/repositorio> \\",
        "  --output <directorio de salida>",
        "```",
        "",
    ]
    if manifest.limitations:
        lines += ["## Limitaciones declaradas", "", *[f"- {item}" for item in dict.fromkeys(manifest.limitations)], ""]
    return "\n".join(lines)


def build_suite(document, plans: list[PlannedVerification], candidates: list[dict],
                validation_records: list[ValidationRecord], limitations: list[str],
                output_zip: Path, *, suite_id: str | None = None, audit_id: str | None = None,
                results: list[VerificationResult] | None = None) -> tuple[ProbeManifest, Path]:
    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    repository_id = (document.repository_id or "unknown") if document is not None else "unknown"
    audit_id = audit_id or repository_id
    suite_id = suite_id or resolve_suite_id(audit_id)

    stage, root = stage_suite_root()
    try:
        copy_templates(root, readme_replacements={
            "__AUDIT_ID__": str(audit_id),
            "__SOURCE_COMMIT__": document.commit if document else "",
        })

        lock_limitation = try_uv_lock(root)
        if lock_limitation:
            limitations = [*limitations, lock_limitation]

        for candidate in candidates:
            content = candidate.get("content")
            if content:
                path = root / candidate["test_path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

        node_plans = [plan for plan in plans if plan.framework != "pytest"]
        if node_plans:
            manifest_language = "mixed" if len(node_plans) != len(plans) else node_plans[0].language
        else:
            manifest_language = "python"

        records_by_id = {record.verification_id: record for record in validation_records}
        verifications = []
        for plan in plans:
            candidate = next((item for item in candidates if item["verification_id"] == plan.verification_id), None)
            record = records_by_id.get(plan.verification_id)
            verifications.append(ProbeManifestVerification(
                verification_id=plan.verification_id,
                finding_id=plan.finding_id,
                test_path=plan.test_path,
                test_name=plan.test_name,
                strategy=plan.strategy,
                covered_property=plan.property,
                target_components=plan.target_components,
                generated_by=(candidate or {}).get("generated_by"),
                generation_status=record.status if record else "not_generated",
                coverage_limitations=plan.limits,
                condition=plan.condition,
                evidence_refs=list(plan.evidence_refs),
                source_commit=document.commit if document else "",
                language=plan.language,
                framework=plan.framework,
            ))

        manifest = ProbeManifest(
            generator=GENERATOR_ID,
            generator_version=GENERATOR_VERSION,
            audit_id=str(audit_id),
            source_commit=document.commit if document else "",
            suite_id=suite_id,
            verifications=verifications,
            language=manifest_language,
            framework="mixed" if node_plans else "pytest",
            limitations=list(dict.fromkeys(limitations)),
        )
        (root / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        report = _report_markdown(document, plans, results or [], validation_records, manifest)
        (root / "docs" / "verification-report.md").write_text(report, encoding="utf-8")
        write_suite_zip(stage, root, output_zip)
        return manifest, output_zip
    finally:
        shutil.rmtree(stage, ignore_errors=True)
