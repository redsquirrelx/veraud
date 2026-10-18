import re
from pathlib import Path
from typing import List
from ..schemas import Finding

SECRET_PATTERNS = [
    {"id": "SEC-AWS-001", "name": "AWS Access Key", "severity": "CRITICAL", "regex": r"(?:AKIA|ASIA)[0-9A-Z]{16}"},
    {"id": "SEC-GHP-002", "name": "GitHub Token", "severity": "CRITICAL", "regex": r"ghp_[a-zA-Z0-9]{36}"},
    {"id": "SEC-PWD-003", "name": "Hardcoded Password", "severity": "HIGH", "regex": r"(?i)(?:password|passwd|secret)\s*[:=]\s*[\"'][^\"']{6,}[\"']"}
]

class SecretScannerAgent:
    def scan_path(self, target_path: str) -> List[Finding]:
        findings = []
        path = Path(target_path)
        files = list(path.rglob("*")) if path.is_dir() else [path]
        count = 1

        for f in files:
            if not f.is_file() or f.suffix.lower() in ('.vdi', '.db', '.png', '.pyc'):
                continue
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                    lines = fp.readlines()
            except Exception:
                continue

            for line_num, text in enumerate(lines, 1):
                clean = text.strip()
                for rule in SECRET_PATTERNS:
                    match = re.search(rule["regex"], clean)
                    if match:
                        findings.append(Finding(
                            finding_id=f"FIND-SEC-{count:04d}",
                            file_path=str(f),
                            line_number=line_num,
                            rule_id=rule["id"],
                            rule_name=rule["name"],
                            severity=rule["severity"],
                            category="Exposed Credentials",
                            owasp_category="A07:2025 - Identification and Authentication Failures",
                            snippet=clean,
                            matched_text=match.group(0)
                        ))
                        count += 1
        return findings
