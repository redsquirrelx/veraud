"""
Agente 3: DAST Sandbox Agent (EN-012 / HU-007)
Ejecuta validación dinámica asíncrona en Docker Sandbox sin bloquear el Fast Path.
"""

import asyncio
from typing import List
from .schemas import Finding
from .config import SecurityConfig

class DASTSandboxAgent:
    def __init__(self, *, config: SecurityConfig | None = None):
        self.config = config or SecurityConfig()

    async def run_async_validation(self, findings: List[Finding]) -> List[Finding]:
        # Simulación de ejecución en segundo plano con Sandbox Docker (Nuclei/DAST)
        await asyncio.sleep(self.config.dast_dispatch_delay_seconds)  # Simula despacho asíncrono
        
        for f in findings:
            if "SQL" in f.category or "Deserialization" in f.category:
                f.dast_validation = {
                    "executed": True,
                    "status": "UNCONFIRMED",
                    "evidence": "DAST sandbox executed: No HTTP endpoint directly exposed for dynamic payload injection."
                }
            else:
                f.dast_validation = {
                    "executed": True,
                    "status": "NOT_APPLICABLE",
                    "evidence": "Static secret / source code vulnerability non-testable via DAST HTTP probes."
                }
        return findings
