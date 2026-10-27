import sqlite3
from contextlib import closing
from pathlib import Path

from ..config import SecurityConfig
from ..schemas import Finding


class KnowledgeEnrichmentAgent:
    def __init__(self, db_path: str | None = None, *, config: SecurityConfig | None = None):
        self.config = config or SecurityConfig()
        self.db_path = Path(db_path if db_path is not None else self.config.knowledge_database_path)

    def enrich(self, findings: list[Finding]) -> list[Finding]:
        if not self.db_path.exists():
            return findings
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                for finding in findings:
                    code = finding.owasp_category.split(":")[0].strip()
                    cursor.execute("SELECT title, cwes FROM owasp_top10 WHERE code = ?", (code,))
                    row = cursor.fetchone()
                    if row:
                        finding.owasp_official_title = row["title"]
                        finding.associated_cwes = row["cwes"]
        except sqlite3.Error:
            return findings
        return findings
