import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

from pydantic import BaseModel

from server.api.schemas import ExecutionConfig
from server.app.execution_service import AgentExecutionService
from server.app.tracing_port import NoOpTracingBackend
from server.blackboard.impls.memory import MemoryBlackboard
from server.runtimes.investigation.agent import InvestigationAgent
from server.runtimes.investigation.schemas import AuditResult


def test_execution_service_injects_blackboard_per_run(monkeypatch):
    monkeypatch.setattr("server.app.execution_service.tracing.setup", lambda: None)
    service = AgentExecutionService(tracing_backend=NoOpTracingBackend())
    boards = [MemoryBlackboard(), MemoryBlackboard()]
    seen = []

    class Output(BaseModel):
        summary: str = "done"

    class Agent:
        input_schema = Output

        def __init__(self):
            self.model = SimpleNamespace(settings=SimpleNamespace(name="offline"))

        async def run(self, payload):
            seen.append(self.blackboard)
            return payload

    monkeypatch.setattr(service, "build_agent", lambda *args: (Agent(), 60))
    for board in boards:
        result = asyncio.run(service.run("offline", ExecutionConfig(), {}, blackboard=board))
        assert result.summary == "done"
    assert seen == boards


def test_investigator_execution_receives_injected_blackboard():
    board = MemoryBlackboard()
    result = AuditResult(
        repository_id="repo", commit=None, snapshot_hash="snapshot", objective="Inspect",
        plan=None, findings=[], hypotheses=[], missing_information=[], limitations=[],
        termination_reason="sufficient_evidence", model_calls=0, tool_calls=0,
        iterations=0, accounted_tokens=0, estimated_tokens=0,
    )

    class Execution:
        def __init__(self, model, config, tools, request):
            self.graph = self
            self.timing = SimpleNamespace(stage=lambda _: nullcontext(), publication_allowed=True)

        def initial_state(self):
            return {}

        def references(self):
            return []

        async def ainvoke(self, state, options):
            assert self.blackboard is board
            return {"result": result}

    class Agent(InvestigationAgent):
        agent_type = "offline"
        execution_type = Execution

    agent = Agent(object(), blackboard=board)
    tools = SimpleNamespace(budget_usage=SimpleNamespace(tool_calls=0), tool_measurements=[])
    assert asyncio.run(agent.run(tools)) is result
