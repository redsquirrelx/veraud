"""Merge agent-built verification-suite ZIPs into one unified deliverable.

Each agent builds its own ``.tallercito/`` package (same runner, same layout).
The merge copies their test suites into a fresh, template-provided root,
rewrites the manifest (union of verifications, generator-aware ``group``
tagging), renders one combined report, resolves one ``uv.lock`` and writes the
unified ZIP. Deterministic and offline; called by the verification-suite
composition only.
"""

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .zip_pack import copy_templates, stage_suite_root, try_uv_lock, write_suite_zip

DEFAULT_GROUP = "other"

__all__ = ["AgentArtifact", "load_agent_zip", "merge_suite_zips"]


@dataclass
class AgentArtifact:
    generator: str
    zip_path: Path
    manifest: dict
    suite_id: str
    termination_reason: str = ""
    validation_status: str = "not_run"
    limitations: list[str] = field(default_factory=list)
    verification_results: list[dict] = field(default_factory=list)

    @property
    def verification_count(self) -> int:
        return len(self.manifest.get("verifications", []))


def load_agent_zip(zip_path: str | Path, generator: str, *, termination_reason: str = "",
                   validation_status: str = "not_run", limitations: list[str] | None = None,
                   verification_results: list[dict] | None = None) -> AgentArtifact:
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        manifest = json.loads(archive.read(".tallercito/manifest.json"))
    limitations = list(limitations if limitations is not None else manifest.get("limitations", []))
    return AgentArtifact(
        generator=generator,
        zip_path=zip_path,
        manifest=manifest,
        suite_id=str(manifest.get("suite_id") or "unknown"),
        termination_reason=termination_reason,
        validation_status=validation_status,
        limitations=limitations,
        verification_results=list(verification_results or []),
    )


def _extract(zip_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            candidate = (destination_resolved / member).resolve()
            try:
                candidate.relative_to(destination_resolved)
            except ValueError as error:
                raise ValueError(f"Archive entry escapes destination: {member!r}") from error
        archive.extractall(destination)


def _generator_label(generator: str) -> str:
    return {"finding_test_generation": "Mantenibilidad",
            "testability_probe": "Testabilidad"}.get(generator, generator)


def _report_markdown(audit_id: str, source_commit: str, suite_id: str,
                     manifest: dict, agent_docs: dict[str, str],
                     generators: list[str]) -> str:
    verifications = manifest.get("verifications", [])
    groups: dict[str, int] = {}
    for verification in verifications:
        group = verification.get("group") or DEFAULT_GROUP
        groups[group] = groups.get(group, 0) + 1
    lines = [
        f"# Verification report — auditoría {audit_id}",
        "",
        "| | |",
        "|---|---|",
        f"| **Auditoría** | `{audit_id}` |",
        f"| **Commit fuente** | `{source_commit or 'desconocido'}` |",
        f"| **Generada** | {datetime.now(UTC).isoformat(timespec='seconds')} |",
        f"| **Suite** | `{suite_id}` · generador `tallercito-verification-suite` |",
        f"| **Verificaciones** | {len(verifications)} ({', '.join(f'{count} {name}' for name, count in sorted(groups.items())) or 'sin verificaciones'}) |",
        f"| **Generadores** | {', '.join(dict.fromkeys(_generator_label(item) for item in generators))} |",
        "",
        ("> **Importante:** esta suite comprueba condiciones concretas de hallazgos ya identificados. "
         "No revisa ni corrige el código auditado, ni cambia el `verification_status` de ningún hallazgo. "
         "Un pase aislado solo indica que la condición no se observó en ese alcance; nunca prueba una corrección (`INCONCLUSIVE`)."),
        "",
        "## Cómo ejecutar esta suite",
        "",
        "```sh",
        "./run.sh                    # Todas las verificaciones",
        "./run.sh --list-groups      # Grupos presentes en el manifiesto",
        "./run.sh --only testability # Solo un subconjunto (grupo)",
        "```",
        "",
        "## Índice de verificaciones",
        "",
        "| Verificación | Grupo | Generador | Hallazgo | Condición |",
        "|---|---|---|---|---|",
    ]
    for verification in verifications:
        generator = verification.get("generator", "")
        condition = (verification.get("condition") or verification.get("covered_property") or "").replace("|", "\\|").replace("\n", " ")[:160]
        lines.append(f"| `{verification.get('verification_id')}` | `{verification.get('group') or DEFAULT_GROUP}` | "
                     f"{_generator_label(generator)} | `{verification.get('finding_id')}` | {condition} |")
    lines.append("")
    if agent_docs:
        for generator, body in agent_docs.items():
            lines += [f"## Detalle — {_generator_label(generator)}", "", body, ""]
    if manifest.get("limitations"):
        lines += ["## Limitaciones declaradas", "", *[f"- {item}" for item in dict.fromkeys(manifest["limitations"])], ""]
    return "\n".join(lines)


def build_empty_suite(output_zip: str | Path, *, audit_id: str, source_commit: str) -> tuple[dict, list[str]]:
    """Empty-but-valid unified suite for audits with zero findings."""

    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    stage, root = stage_suite_root()
    try:
        copy_templates(root, readme_replacements={
            "__AUDIT_ID__": str(audit_id),
            "__SOURCE_COMMIT__": str(source_commit or ""),
        })
        manifest = {
            "schema_version": "1.1",
            "generator": "tallercito-verification-suite",
            "generator_version": "1.0",
            "audit_id": str(audit_id),
            "source_commit": str(source_commit or ""),
            "suite_id": f"audit-{str(audit_id)[:32]}-empty",
            "runner": "uv",
            "root_layout": ".tallercito",
            "language": "python",
            "framework": "pytest",
            "verifications": [],
            "limitations": [("No findings were received for this audit; the suite contains nothing to verify. "
                             "This does not certify the repository is defect-free.")],
        }
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
        write_suite_zip(stage, root, output_zip)
        return manifest, list(manifest["limitations"])
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def merge_suite_zips(output_zip: str | Path, artifacts: list[AgentArtifact], *,
                     audit_id: str, source_commit: str,
                     verification_groups: dict[str, str],
                     extra_limitations: list[str] | None = None) -> tuple[dict, list[str]]:
    """Build the unified suite ZIP; return (merged manifest, limitations)."""
    if not artifacts:
        raise ValueError("merge_suite_zips requires at least one agent artifact")
    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    from datetime import (
        datetime as _datetime,  # local alias: avoid shadowing in embedded f-strings
    )

    suite_id = f"audit-{str(audit_id).replace('-', '_')[:32]}-{_datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    stage, root = stage_suite_root()
    copy_templates(root, readme_replacements={
        "__AUDIT_ID__": str(audit_id),
        "__SOURCE_COMMIT__": str(source_commit or ""),
    })
    agent_docs: dict[str, str] = {}
    renamed_paths: dict[str, str] = {}
    try:
        for position, artifact in enumerate(artifacts):
            extracted = stage / f".extract-{position}"
            extracted.mkdir(parents=True, exist_ok=True)
            _extract(artifact.zip_path, extracted)
            src = extracted / ".tallercito"
            for path in (src / "tests").rglob("*") if (src / "tests").is_dir() else []:
                if not path.is_file():
                    continue
                rel = path.relative_to(src)
                rel_posix = rel.as_posix()
                destination = root / rel
                if destination.exists():
                    destination = destination.with_name(f"{destination.stem}_{artifact.generator}{destination.suffix}")
                    renamed_paths[rel_posix] = destination.relative_to(root).as_posix()
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
            docs = src / "docs" / "verification-report.md"
            if docs.is_file():
                agent_docs[artifact.generator] = docs.read_text(encoding="utf-8")
            shutil.rmtree(extracted, ignore_errors=True)

        verifications: list[dict] = []
        limitations: list[str] = []
        for artifact in artifacts:
            for entry in artifact.manifest.get("verifications", []):
                merged = dict(entry)
                merged["generator"] = artifact.generator
                merged["group"] = verification_groups.get(entry.get("finding_id", "")) or DEFAULT_GROUP
                if merged.get("test_path") in renamed_paths:
                    merged["test_path"] = renamed_paths[merged["test_path"]]
                verifications.append(merged)
            limitations.extend(artifact.limitations)
        if renamed_paths:
            limitations.append(f"Renamed tests to avoid collisions: {', '.join(sorted(renamed_paths))}")
        if extra_limitations:
            limitations.extend(extra_limitations)

        merged_manifest = {
            "schema_version": "1.1",
            "generator": "tallercito-verification-suite",
            "generator_version": "1.0",
            "audit_id": str(audit_id),
            "source_commit": str(source_commit or ""),
            "suite_id": suite_id,
            "runner": "uv",
            "root_layout": ".tallercito",
            "language": "python",
            "framework": "pytest",
            "verifications": verifications,
            "limitations": list(dict.fromkeys(limitations)),
        }

        lock_limitation = try_uv_lock(root)
        if lock_limitation:
            merged_manifest["limitations"] = [*merged_manifest["limitations"], lock_limitation]

        (root / "manifest.json").write_text(json.dumps(merged_manifest, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
        (root / "docs" / "verification-report.md").write_text(
            _report_markdown(str(audit_id), str(source_commit or ""), suite_id, merged_manifest, agent_docs,
                             [artifact.generator for artifact in artifacts]),
            encoding="utf-8")
        write_suite_zip(stage, root, output_zip)
        return merged_manifest, list(merged_manifest["limitations"])
    finally:
        shutil.rmtree(stage, ignore_errors=True)
