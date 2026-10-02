import uvicorn

from .config.settings import settings


def dev():
    uvicorn.run(
        "server.main:app",
        host = "localhost",
        port = settings.port_agentserver,
        reload = True,
    )