import os
from pathlib import Path

import uvicorn
from config.settings import settings

def dev():
    uvicorn.run(
        "api.main:app",
        host = "localhost",
        port = settings.port_agentserver,
        reload = True,
    )