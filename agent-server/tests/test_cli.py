"""Development reloads watch project sources, not installed dependencies."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from server import cli


def test_dev_limits_reload_to_source_and_configuration(monkeypatch):
    run = Mock()
    monkeypatch.setattr(cli.uvicorn, "run", run)
    monkeypatch.setattr(
        "server.config.settings.get_server_settings",
        lambda: SimpleNamespace(port_agentserver=8765),
    )

    cli.dev()

    root = Path(cli.__file__).resolve().parents[2]
    run.assert_called_once_with(
        "server.main:app",
        host="localhost",
        port=8765,
        reload=True,
        reload_dirs=[str(root / "src"), str(root / "config")],
    )
