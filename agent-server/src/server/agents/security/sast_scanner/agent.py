import re
from pathlib import Path
from typing import List
from ..schemas import Finding

SAST_RULES = [
    {
        "id": "SQLI-001",
        "name": "SQL Injection via String Concatenation",
        "severity": "HIGH",
        "category": "SQL Injection",
        "owasp": "A03:2025 - Injection",
        "languages": ["python", "node", "java"],
        "regex": r"(?i)(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE).*?['\"]?\s*\+\s*|\$\{.*?\}|String\.format\(|\bquery\s*\(.*?\+"
    },
    {
        "id": "DESER-001",
        "name": "Insecure Deserialization",
        "severity": "CRITICAL",
        "category": "Insecure Deserialization",
        "owasp": "A08:2025 - Software Integrity",
        "languages": ["python", "node", "java"],
        "regex": r"\bpickle\.(?:loads|load)\s*\(|\bserialize\.unserialize\s*\(|\.readObject\s*\(\s*\)"
    }
]

class SASTScannerAgent:
    def scan_path(self, target_path: str) -> List[Finding]:
        findings = []
        path = Path(target_path)
        files = list(path.rglob("*")) if path.is_dir() else [path]
        count = 1

        for f in files:
            if not f.is_file() or f.suffix.lower() not in ('.py', '.js', '.java'):
                continue
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                    lines = fp.readlines()
            except Exception:
                continue

            for line_num, text in enumerate(lines, 1):
                clean = text.strip()
                for rule in SAST_RULES:
                    match = re.search(rule["regex"], clean)
                    if match:
                        findings.append(Finding(
                            finding_id=f"FIND-SAST-{count:04d}",
                            file_path=str(f),
                            line_number=line_num,
                            rule_id=rule["id"],
                            rule_name=rule["name"],
                            severity=rule["severity"],
                            category=rule["category"],
                            owasp_category=rule["owasp"],
                            snippet=clean,
                            matched_text=match.group(0)
                        ))
                        count += 1
        return findings
