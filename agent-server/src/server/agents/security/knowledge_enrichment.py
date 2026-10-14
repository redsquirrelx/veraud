"""
Agente 2: Knowledge Enrichment Agent (EN-010)
Enriquece hallazgos consultando la BD local SQLite `security_patterns.db` (<50ms).
"""

import sqlite3
from pathlib import Path
from typing import List
from .schemas import Finding

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
                owasp_code = f.owasp_category.split(":")[0].strip()
                cursor.execute("SELECT title, description, cwes FROM owasp_top10 WHERE code = ?", (owasp_code,))
                row = cursor.fetchone()
                if row:
                    f.owasp_official_title = row["title"]
                    f.associated_cwes = row["cwes"]

                # Verificación de prioridad CISA KEV (Signal Check)
                cursor.execute("SELECT COUNT(*) as cnt FROM cisa_kev")
                kev_row = cursor.fetchone()
                if kev_row and kev_row["cnt"] > 0 and "SQL" in f.category:
                    f.cisa_kev_match = True

            conn.close()
        except Exception:
            pass

        return findings