"""Step 1: backend and agent-server share one checkout root.

The backend clones into the repo appdata/workspace unless WORKSPACE_DIR is
set; the agent-server resolves the same root unless WORKSPACE_ROOT is set.
"""

from pathlib import Path

from server.config.settings import clear_cache, find_repo_root, resolve_workspace_root

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_is_the_repo_workspace():
    clear_cache()
    try:
        assert resolve_workspace_root() == REPO_ROOT / "appdata" / "workspace"
    finally:
        clear_cache()

def test_env_override_relocates_the_root(tmp_path, monkeypatch):
    monkeypatch.setenv("PORT_BACKEND", "7501")
    monkeypatch.setenv("PORT_AGENTSERVER", "7502")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "shared"))
    clear_cache()
    try:
        assert resolve_workspace_root() == (tmp_path / "shared").resolve()
    finally:
        clear_cache()


def test_blank_override_keeps_the_default(monkeypatch):
    monkeypatch.setenv("PORT_BACKEND", "7501")
    monkeypatch.setenv("PORT_AGENTSERVER", "7502")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("WORKSPACE_ROOT", "  ")
    clear_cache()
    try:
        assert resolve_workspace_root() == REPO_ROOT / "appdata" / "workspace"
    finally:
        clear_cache()


def test_find_repo_root_by_marker(tmp_path):
    nested = tmp_path / "backend" / "src" / "config"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) is None
    (tmp_path / ".git").mkdir()
    assert find_repo_root(nested) == tmp_path.resolve()
