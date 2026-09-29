import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

def dev():
    uvicorn.run(
        "server.main:app",
        host = "localhost",
        port = int(os.getenv("PORT_AGENTSERVER", "8000")),
        reload = True,
    )