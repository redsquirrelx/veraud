"""Every environment variable the server reads, and where it comes from.

Two groups, split because they fail differently:

- ServerSettings   required. A missing value is a deployment mistake.
- TracingSettings  optional, with a default for everything. LangSmith tracing is
  off unless a key is present, so its absence must never break an import.

Both read the repo's .env. The path is resolved from this file rather than from
the working directory, because agent-server/src/server/config sits four levels
below the root and the dev runners are run from anywhere.

Instances are built on demand, not at import. The dev runners must work with no
.env at all, so importing this module has to be safe; cli.dev and the
representations runners rely on that.

Note that nothing here writes to os.environ. Pydantic reads the file into its own
fields, so a variable declared here is not visible to code reading the
environment. LangSmith reads LANGSMITH_ENDPOINT and LANGSMITH_TRACING that way,
which is why config/tracing.py passes them across explicitly.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# agent-server/src/server/config -> up four is the repo root.
ENV_FILE = Path(__file__).resolve().parents[4] / ".env"

LANGSMITH_CLOUD = "https://api.smith.langchain.com"


class _FromEnvFile(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ServerSettings(_FromEnvFile):
    """What the server needs to start and reach a model."""

    environment: str = "development"
    port_backend: int
    port_agentserver: int
    llm_api_key: str


class TracingSettings(_FromEnvFile):
    """LangSmith tracing. Off unless a key is set."""

    langsmith_api_key: str = ""
    langsmith_project: str = "agent-server"
    langsmith_endpoint: str = LANGSMITH_CLOUD
    langsmith_tags: str = ""
    langsmith_hide_inputs: bool = False
    langsmith_hide_outputs: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.langsmith_api_key.strip())

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.langsmith_tags.split(",") if tag.strip()]


@lru_cache(maxsize=1)
def get_server_settings() -> ServerSettings:
    """Build the server settings, reading the .env the first time.

    Raises ValidationError when a required value is missing, which is the
    intended failure: the server cannot start without them.
    """
    return ServerSettings()


@lru_cache(maxsize=1)
def get_tracing_settings() -> TracingSettings:
    """Build the tracing settings. Always succeeds: every field has a default."""
    return TracingSettings()


def clear_cache() -> None:
    """Forget the built settings, so the next call re-reads the .env."""
    get_server_settings.cache_clear()
    get_tracing_settings.cache_clear()