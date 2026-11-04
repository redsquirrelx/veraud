from fastapi.testclient import TestClient

from server.blackboard.impls.memory import MemoryBlackboard
from server.main import app


def test_blackboard_is_shared_during_lifespan_and_recreated_on_restart():
    with TestClient(app) as client:
        blackboard = app.state.blackboard
        assert isinstance(blackboard, MemoryBlackboard)

        assert client.get("/api/status").status_code == 200
        assert app.state.blackboard is blackboard

    assert not hasattr(app.state, "blackboard")

    with TestClient(app):
        assert isinstance(app.state.blackboard, MemoryBlackboard)
        assert app.state.blackboard is not blackboard
