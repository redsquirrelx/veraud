"""FindingTestGenerationAgent — standalone prototype for audit-140 verification suites.

Deliberately unregistered: no HTTP surface, backend callbacks, database or
pipelines until a later integration milestone approves them.

The LLM is a rule selector and nothing more: it never authors or repairs test
code. All test content is rendered from deterministic templates; the green
control is a rejection gate (unproven tests are dropped), not a repair loop.
"""

from .config import FindingTestConfig
from .execution import FindingTestGenerationExecution
from .schemas import FindingTestGenerationRequest, FindingTestGenerationResult


class FindingTestGenerationAgent:
    trace_name = "finding-test-generation"
    agent_type = "finding_test_generation"

    def __init__(self, model=None, config: FindingTestConfig | None = None, llm_client=None):
        # `model` is accepted for forward compatibility; local model wiring uses the injected llm_client.
        self.model = getattr(model, "llm", model)
        self.config = config or FindingTestConfig()
        self.llm_client = llm_client

    async def run(self, request: FindingTestGenerationRequest | dict) -> FindingTestGenerationResult:
        request = FindingTestGenerationRequest.model_validate(request)
        execution = FindingTestGenerationExecution(self.config, self.llm_client)
        final_state = await execution.graph.ainvoke(
            execution.initial_state(request), {"recursion_limit": 40})
        return final_state["result"]
