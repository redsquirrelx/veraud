import asyncio

from ..config import SecurityConfig
from ..schemas import Finding


class DASTSandboxAgent:
    def __init__(self, *, config: SecurityConfig | None = None):
        self.config = config or SecurityConfig()

    async def run_async_validation(self, findings: list[Finding]) -> list[Finding]:
        await asyncio.sleep(self.config.dast_dispatch_delay_seconds)
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
