from pathlib import Path

import uvicorn


def dev():
    # Imported here, not at module level: the dev runners need no .env, and an
    # eager import would force one on every entry point in this file.
    from .config.settings import get_server_settings

    project_root = Path(__file__).resolve().parents[2]
    uvicorn.run(
        "server.main:app",
        host = "localhost",
        port = get_server_settings().port_agentserver,
        reload = True,
        reload_dirs = [str(project_root / "src"), str(project_root / "config")],
    )
