"""
Agente 1: SAST & Secret Scanner Agent (TA-005 / HU-009)
Analiza AST/Regex en Python, Node.js, Java y archivos de configuración.
"""

import re
import ast
from pathlib import Path
from typing import List
from .schemas import Finding

SAST_RULES = [
    {
        "id": "SEC-001",
        "name": "Hardcoded AWS Access Key",
        "severity": "CRITICAL",
        "category": "Exposed Credentials",
        "owasp": "A07:2025 - Identification and Authentication Failures",
        "languages": ["python", "node", "java", "config"],
        "regex": r"(?:AKIA|ASIA)[0-9A-Z]{16}"
    },
    {
        "id": "SEC-002",
        "name": "Hardcoded Password or Private Secret",
        "severity": "HIGH",
        "category": "Exposed Credentials",
        "owasp": "A07:2025 - Identification and Authentication Failures",
        "languages": ["python", "node", "java", "config"],
        "regex": r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[\"'][^\"']{6,}[\"']"
    },
    {
        "id": "SQLI-001",
        "name": "SQL Injection via String Concatenation/Interpolation",
        "severity": "HIGH",
        "category": "SQL Injection",
        "owasp": "A03:2025 - Injection",
        "languages": ["python", "node", "java"],
        "regex": r"(?i)(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE).*?['\"]?\s*\+\s*|\$\{.*?\}|String\.format\(|\bquery\s*\(.*?\+"
    },
    {
        "id": "DESER-001",
        "name": "Insecure Python Pickle Deserialization",
        "severity": "CRITICAL",
        "category": "Insecure Deserialization",
        "owasp": "A08:2025 - Software and Data Integrity Failures",
        "languages": ["python"],
        "regex": r"\bpickle\.(?:loads|load)\s*\("
    },
    {
        "id": "DESER-002",
        "name": "Insecure Node.js Deserialization",
        "severity": "CRITICAL",
        "category": "Insecure Deserialization",
        "owasp": "A08:2025 - Software and Data Integrity Failures",
        "languages": ["node"],
        "regex": r"\b(?:serialize\.unserialize|funcster\.unserialize)\s*\("
    },
    {
        "id": "DESER-003",
        "name": "Insecure Java ObjectInputStream Deserialization",
        "severity": "CRITICAL",
        "category": "Insecure Deserialization",
        "owasp": "A08:2025 - Software and Data Integrity Failures",
        "languages": ["java"],
        "regex": r"\.readObject\s*\(\s*\)"
    }
]

class SASTScannerAgent:
    def detect_language(self, filepath: Path) -> str:
        ext = filepath.suffix.lower()
        if ext == ".py":
            return "python"
        elif ext in (".js", ".ts"):
            return "node"
        elif ext == ".java":
            return "java"
        elif ext in (".env", ".json", ".yaml", ".yml", ".ini"):
            return "config"
        return "unknown"

    def scan_path(self, target_path: str) -> List[Finding]:
        findings = []
        path = Path(target_path)
        
        files_to_scan = list(path.rglob("*")) if path.is_dir() else [path]
        count = 1

        for file_p in files_to_scan:
            if not file_p.is_file():
                continue
            lang = self.detect_language(file_p)
            if lang == "unknown":
                continue

            try:
                with open(file_p, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except Exception:
                continue

            for line_num, line_text in enumerate(lines, 1):
                clean_text = line_text.strip()
                for rule in SAST_RULES:
                    if lang in rule["languages"]:
                        match = re.search(rule["regex"], clean_text)
                        if match:
                            f_obj = Finding(
                                finding_id=f"FIND-SEC-{count:04d}",
                                file_path=str(file_p),
                                line_number=line_num,
                                rule_id=rule["id"],
                                rule_name=rule["name"],
                                severity=rule["severity"],
                                category=rule["category"],
                                owasp_category=rule["owasp"],
                                snippet=clean_text,
                                matched_text=match.group(0)
                            )
                            findings.append(f_obj)
                            count += 1
        return findings