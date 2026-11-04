import sqlite3
import re
import os

DB_PATH = "security_patterns.db"

class SecurityRulesManager:
    """Gestor dinámico de reglas SAST y excepciones en SQLite.
    Permite altas, bajas, modificaciones y alternar el estado activo/inactivo
    en tiempo de ejecución sin reiniciar el servidor.
    """

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Inicializa la tabla de reglas si no existe."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rules (
                    rule_id TEXT PRIMARY KEY,
                    rule_name TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    owasp_category TEXT NOT NULL,
                    cwe TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            """)
            conn.commit()

    def validate_regex(self, pattern: str) -> bool:
        """Valida sintácticamente una expresión regular antes de guardarla."""
        try:
            re.compile(pattern)
            return True
        except re.error as e:
            raise ValueError(f"Expresión regular inválida '{pattern}': {e}")

    def add_rule(self, rule_id: str, rule_name: str, pattern: str, severity: str, owasp_category: str, cwe: str, is_active: int = 1):
        """Agrega una nueva regla SAST previa validación sintáctica del Regex."""
        self.validate_regex(pattern)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO rules (rule_id, rule_name, pattern, severity, owasp_category, cwe, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (rule_id, rule_name, pattern, severity, owasp_category, cwe, is_active))
            conn.commit()
        return True

    def toggle_rule(self, rule_id: str, is_active: bool):
        """Activa (True/1) o deshabilita (False/0) una regla dinámicamente."""
        status_flag = 1 if is_active else 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE rules SET is_active = ? WHERE rule_id = ?", (status_flag, rule_id))
            conn.commit()
        return True

    def get_active_rules(self):
        """Obtiene únicamente las reglas activas (is_active = 1) para el escáner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rule_id, rule_name, pattern, severity, owasp_category, cwe FROM rules WHERE is_active = 1")
            rows = cursor.fetchall()
            return [
                {
                    "rule_id": r[0],
                    "rule_name": r[1],
                    "pattern": r[2],
                    "severity": r[3],
                    "owasp_category": r[4],
                    "cwe": r[5]
                }
                for r in rows
            ]

    def delete_rule(self, rule_id: str):
        """Elimina una regla de la base de datos."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rules WHERE rule_id = ?", (rule_id,))
            conn.commit()
        return True


if __name__ == "__main__":
    manager = SecurityRulesManager()
    
    # 1. Registro / Prueba CRUD de regla
    test_pattern = r"SELECT\s+.*\s+FROM\s+.*"
    manager.add_rule(
        rule_id="DYNAMIC-SQLI-001",
        rule_name="Inyección SQL Dinámica",
        pattern=test_pattern,
        severity="HIGH",
        owasp_category="A03:2025 - Injection",
        cwe="CWE-89",
        is_active=1
    )
    print("[+] Regla 'DYNAMIC-SQLI-001' registrada y regex validado con éxito.")

    # 2. Deshabilitar regla dinámicamente (is_active = 0)
    manager.toggle_rule("DYNAMIC-SQLI-001", is_active=False)
    print("[+] Regla 'DYNAMIC-SQLI-001' deshabilitada dinámicamente (is_active = 0).")

    # 3. Reactivar regla
    manager.toggle_rule("DYNAMIC-SQLI-001", is_active=True)
    active_rules = manager.get_active_rules()
    print(f"[SUCCESS] Total de reglas activas consultadas en caliente: {len(active_rules)}")
