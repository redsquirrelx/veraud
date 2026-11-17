"""TestabilityProbeAgent facade.

Deliberately unregistered for HTTP/catalog exposure: it runs as a CLI until an
integration milestone approves otherwise. The LLM is mandatory — this agent is
not a deterministic detector pipeline.
"""

from __future__ import annotations

import asyncio

from .config import TestabilityProbeConfig
from .execution import TestabilityProbeExecution
from .schemas import ProbeRequest, ProbeResult

DEFAULT_RECURSION_LIMIT = 60


class TestabilityProbeAgent:
    agent_type = "testability_probe"

    def __init__(self, config: TestabilityProbeConfig | None = None, llm_client=None):
        self.config = config or TestabilityProbeConfig()
        self.llm_client = llm_client

    async def run(self, request: ProbeRequest) -> ProbeResult:
        if self.llm_client is None:
            return ProbeResult(
                ok=False,
                termination_reason="llm_unavailable",
                repository_id="",
                total_findings=0,
                validation_status="not_run",
                errors=["TestabilityProbeAgent requires an LLM client (pass llm_client); it has no deterministic fallback."],
            )
        execution = TestabilityProbeExecution(self.config, self.llm_client)
        result = await execution.graph.ainvoke({"request": request}, {"recursion_limit": DEFAULT_RECURSION_LIMIT})
        return result["result"]

    def run_sync(self, request: ProbeRequest) -> ProbeResult:
        return asyncio.run(self.run(request))


__all__ = ["TestabilityProbeAgent"]
