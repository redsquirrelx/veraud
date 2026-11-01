import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


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
