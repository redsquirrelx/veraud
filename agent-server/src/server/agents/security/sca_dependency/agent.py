from pathlib import Path

from ..schemas import Finding

VULN_DEPS = [
    {"name": "requests", "cve": "CVE-2021-33503", "severity": "HIGH"},
    {"name": "express", "cve": "CVE-2022-24999", "severity": "CRITICAL"}
]

class SCADependencyAgent:
    def scan_dependencies(self, target_path: str) -> list[Finding]:
        findings = []
        path = Path(target_path)
        req_files = list(path.rglob("requirements.txt")) + list(path.rglob("package.json"))

        for f in req_files:
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    content = fp.read()
                for dep in VULN_DEPS:
                    if dep["name"] in content:
                        findings.append(Finding(
                            finding_id="FIND-SCA-001",
                            file_path=str(f),
                            line_number=1,
                            rule_id=dep["cve"],
                            rule_name=f"Vulnerable Dependency: {dep['name']}",
                            severity=dep["severity"],
                            category="Vulnerable Components",
                            owasp_category="A06:2025 - Vulnerable Components",
                            snippet=f"Dependency {dep['name']} identified in manifest",
                            matched_text=dep["name"]
                        ))
            except OSError:
                pass
        return findings
