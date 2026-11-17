"""Ejecutar desde agent-server (PowerShell):

    uv run python src/test-agents/run_finding_test_generation.py `
        --findings fixtures/audit_140/findings.json `
        --repo ../appdata/workspace/1454248654-redsquirrelx-urban-mesh `
        --output ./artifacts/audit-140

Genera la suite de verificación portable (.tallercito/) como ZIP. El LLM, con
`--llm provider`, solo selecciona la regla a aplicar por hallazgo y rellena sus
parámetros validados; los tests son siempre deterministas y el LLM nunca escribe
ni repara código. No modifica el repositorio auditado. Ver --help para todas las
opciones.
"""

from server.agents.finding_test_generation.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
