import uvicorn


def dev():
    # Imported here, not at module level: the dev runners need no .env, and an
    # eager import would force one on every entry point in this file.
    from .config.settings import get_server_settings

    uvicorn.run(
        "server.main:app",
        host = "localhost",
        port = get_server_settings().port_agentserver,
        reload = True,
    )
