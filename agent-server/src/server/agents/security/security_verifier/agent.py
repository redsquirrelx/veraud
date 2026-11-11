"""Reviewer de hallazgos de seguridad.

Vuelve a ejecutar, sobre una copia aislada (sandbox) del archivo afectado, el mismo
escáner que produjo cada hallazgo y determina si el hallazgo PERSISTE o fue RESUELTO,
con su justificación y evidencia. Es determinista: no invoca modelos, así que no
consume tokens.

Contrato con el resto del pipeline (sin cambios):
- ``SecurityVerifierAgent()`` se construye sin argumentos.
- ``filter_false_positives(list[Finding]) -> list[Finding]`` devuelve los hallazgos
  que siguen vigentes (persisten o no se pudieron verificar); descarta los resueltos.
"""

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..sast_scanner.agent import SAST_RULES, SASTScannerAgent
from ..schemas import Finding
from ..sca_dependency.agent import VULN_DEPS, SCADependencyAgent
from ..secret_scanner.agent import SECRET_PATTERNS, SecretScannerAgent

PERSISTS = "PERSISTS"
RESOLVED = "RESOLVED"
NOT_VERIFIED = "NOT_VERIFIED"

_SAST_IDS = {rule["id"] for rule in SAST_RULES}
_SECRET_IDS = {rule["id"] for rule in SECRET_PATTERNS}
_SCA_IDS = {dep["cve"] for dep in VULN_DEPS}
_MANIFESTS = {"requirements.txt", "package.json"}


def _redact(text: str) -> str:
    """Normaliza credenciales igual que la publicación, para comparar fragmentos redactados."""
    for pattern in SECRET_PATTERNS:
        text = re.sub(pattern["regex"], "[CREDENCIAL REDACTADA]", text)
    return text.strip()


class SecurityVerifierAgent:
    """Reviewer que re-ejecuta el escáner de origen en sandbox para cada hallazgo."""

    def __init__(self, target_repo_path: str | None = None):
        # Raíz del repositorio para resolver rutas relativas. Sin ella, una ruta
        # relativa inaccesible queda NOT_VERIFIED en vez de declararse resuelta.
        self.target_repo_path = target_repo_path
        self._sast = SASTScannerAgent()
        self._secret = SecretScannerAgent()
        self._sca = SCADependencyAgent()

    # ------------------------------------------------------------------ sandbox
    def _scanner_for(self, rule_id: str) -> str | None:
        if rule_id in _SAST_IDS:
            return "sast"
        if rule_id in _SECRET_IDS:
            return "secret"
        if rule_id in _SCA_IDS:
            return "sca"
        return None

    def _resolve(self, file_path: str) -> tuple[Path | None, bool]:
        """Devuelve (ruta existente o None, si la ausencia es concluyente)."""
        path = Path(file_path)
        if path.is_absolute():
            return (path if path.is_file() else None), True
        if self.target_repo_path:
            candidate = Path(self.target_repo_path) / path
            return (candidate if candidate.is_file() else None), True
        return None, False

    def _rescan(self, source: Path, scanner: str) -> list[Finding]:
        """Copia el archivo a un directorio temporal aislado y re-ejecuta el escáner."""
        with tempfile.TemporaryDirectory(prefix="veraud-verifier-") as sandbox:
            copy = Path(sandbox) / source.name
            shutil.copyfile(source, copy)
            if scanner == "sca":
                return self._sca.scan_dependencies(sandbox) if copy.name in _MANIFESTS else []
            agent = self._sast if scanner == "sast" else self._secret
            return agent.scan_path(str(copy))

    # ----------------------------------------------------------------- revisión
    def verify_finding(self, finding: Finding, cache: dict | None = None) -> dict[str, Any]:
        """Determina si un hallazgo persiste o fue resuelto, con justificación."""
        cache = {} if cache is None else cache
        location = f"{finding.file_path}:{finding.line_number}"
        result = {"finding_id": finding.finding_id, "rule_id": finding.rule_id, "severity": finding.severity,
                  "file_path": finding.file_path, "line_number": finding.line_number}

        def close(status, justification, sandbox=None):
            return {**result, "status": status, "justification": justification,
                    "evidence": {"method": "sandbox_rescan", "scanner": scanner, **(sandbox or {})}}

        scanner = self._scanner_for(finding.rule_id)
        if scanner is None:
            return close(NOT_VERIFIED, f"La regla {finding.rule_id} no pertenece a ningún escáner conocido; "
                         "no se puede re-ejecutar la detección.")
        source, conclusive = self._resolve(finding.file_path)
        if source is None:
            if conclusive:
                return close(RESOLVED, f"El archivo {finding.file_path} ya no existe; el código afectado fue eliminado o movido.",
                             {"executed": False})
            return close(NOT_VERIFIED, f"El archivo {finding.file_path} no es accesible desde el reviewer "
                         "(ruta relativa sin raíz de repositorio); el hallazgo se conserva.", {"executed": False})

        key = (str(source), scanner)
        if key not in cache:
            try:
                cache[key] = self._rescan(source, scanner)
            except OSError as error:
                cache[key] = error
        matches = cache[key]
        if isinstance(matches, OSError):
            return close(NOT_VERIFIED, f"No se pudo copiar {finding.file_path} al sandbox ({type(matches).__name__}); "
                         "el hallazgo se conserva.", {"executed": False})

        same_rule = [m for m in matches if m.rule_id == finding.rule_id]
        snippet = _redact(finding.snippet)
        at_line = next((m for m in same_rule if m.line_number == finding.line_number), None)
        same_code = next((m for m in same_rule if _redact(m.snippet) == snippet), None)
        sandbox = {"executed": True, "rule_matches_in_file": len(same_rule)}

        if scanner == "sca" and same_rule:
            return close(PERSISTS, f"La dependencia vulnerable ({finding.rule_id}) sigue declarada en {finding.file_path}.",
                         sandbox)
        if at_line and _redact(at_line.snippet) == snippet:
            return close(PERSISTS, f"La regla {finding.rule_id} sigue detectándose en {location} con el mismo código.",
                         {**sandbox, "current_line": at_line.line_number, "current_snippet": _redact(at_line.snippet)})
        if same_code:
            return close(PERSISTS, f"El mismo código vulnerable sigue presente en {finding.file_path}, "
                         f"ahora en la línea {same_code.line_number} (antes {finding.line_number}).",
                         {**sandbox, "current_line": same_code.line_number, "current_snippet": _redact(same_code.snippet)})
        if at_line:
            return close(PERSISTS, f"El código de {location} cambió, pero la regla {finding.rule_id} sigue detectándose "
                         "en esa línea.", {**sandbox, "current_line": at_line.line_number,
                                           "current_snippet": _redact(at_line.snippet)})
        others = f" La regla aún detecta {len(same_rule)} coincidencia(s) distintas en el archivo." if same_rule else ""
        return close(RESOLVED, f"Al re-ejecutar el escáner, la regla {finding.rule_id} ya no detecta el código "
                     f"original de {location}.{others}", sandbox)

    def review_all_findings(self, findings: list[Finding]) -> dict[str, Any]:
        """Revisa cada hallazgo y devuelve el informe completo del reviewer."""
        cache: dict = {}
        reviews = [self.verify_finding(f, cache) for f in findings]
        return {
            "reviewer_agent": "SecurityVerifierAgent",
            "summary": {
                "total_findings_reviewed": len(reviews),
                "persisting": sum(r["status"] == PERSISTS for r in reviews),
                "resolved": sum(r["status"] == RESOLVED for r in reviews),
                "not_verified": sum(r["status"] == NOT_VERIFIED for r in reviews),
            },
            "findings_status": reviews,
        }

    def filter_false_positives(self, findings: list[Finding]) -> list[Finding]:
        """Interfaz usada por el pipeline: conserva los hallazgos vigentes y adjunta su revisión."""
        cache: dict = {}
        kept = []
        for finding in findings:
            review = self.verify_finding(finding, cache)
            finding.verified = review["status"] == PERSISTS
            # remediation es un dict del contrato Finding: así la revisión viaja en to_dict().
            finding.remediation["review"] = {key: review[key] for key in ("status", "justification", "evidence")}
            if review["status"] != RESOLVED:
                kept.append(finding)
        return kept


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as repo:
        target = Path(repo) / "app.py"
        target.write_text("import pickle\ndata = pickle.loads(payload)\n", encoding="utf-8")
        found = SASTScannerAgent().scan_path(str(target))
        reviewer = SecurityVerifierAgent()
        print(json.dumps(reviewer.review_all_findings(found), indent=2, ensure_ascii=False))
        target.write_text("import json\ndata = json.loads(payload)\n", encoding="utf-8")
        print(json.dumps(reviewer.review_all_findings(found), indent=2, ensure_ascii=False))
