import uvicorn


def dev():
    # Imported here, not at module level: the repomap runner needs no .env,
    # and an eager import would force one on every entry point in this file.
    from .config.settings import settings

    uvicorn.run(
        "server.main:app",
        host = "localhost",
        port = settings.port_agentserver,
        reload = True,
    )