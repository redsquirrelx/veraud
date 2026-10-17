import sqlite3
from pathlib import Path
from typing import List
from ..schemas import Finding

class KnowledgeEnrichmentAgent:
    def __init__(self, db_path: str = "security_patterns.db"):
        self.db_path = Path(db_path)

    def enrich(self, findings: List[Finding]) -> List[Finding]:
        if not self.db_path.exists():
            return findings
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            for f in findings:
                code = f.owasp_category.split(":")[0].strip()
                cursor.execute("SELECT title, cwes FROM owasp_top10 WHERE code = ?", (code,))
                row = cursor.fetchone()
                if row:
                    f.owasp_official_title = row["title"]
                    f.associated_cwes = row["cwes"]
            conn.close()
        except Exception:
            pass
        return findings
