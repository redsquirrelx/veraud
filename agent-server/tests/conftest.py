import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(autouse=True)
def enabled_agent_budgets(monkeypatch):
    """Tests use finite budgets regardless of the operator's launch settings."""
    from config.agents.budgets import BudgetPolicy
    from server.agent_services.budgeting import policy

    monkeypatch.setattr(policy, "token_budget_policy", lambda: BudgetPolicy(budgets_enabled=True))


@pytest.fixture(autouse=True)
def isolated_execution_event_delivery(tmp_path, monkeypatch):
    """Tests must never replay fixture execution IDs to a running real backend."""
    from server.infrastructure import execution_event_buffer as outbox
    from server.infrastructure import execution_events as history

    journals = []

    def journal():
        if not journals:
            journals.append(outbox.ExecutionEventBuffer())
        return journals[0]

    async def offline_delivery(stop, sink_factory):
        await stop.wait()

    monkeypatch.setattr(history, "execution_event_buffer", journal)
    monkeypatch.setattr(outbox, "execution_event_buffer", journal)
    monkeypatch.setattr(outbox, "execution_event_delivery_worker", offline_delivery)
