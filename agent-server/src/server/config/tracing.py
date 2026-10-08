"""LangSmith tracing for agent runs.

Off unless LANGSMITH_API_KEY is set. The installed client traces by default and
raises on a bad key rather than quietly doing nothing, so the key is the switch:
with one, every agent run produces a trace; without one, this module is a
pass-through and the agents do exactly what they did before.

The trace looks like this:

    analyzer            one span per agent execution
      LangGraph         the graph, traced automatically
        hypothesize     one span per node
          gemini/flash  one span per model call, under the node that made it

LangGraph and the model calls share a single Client, so it all lands in one tree
instead of a scatter of orphans.

Every variable is declared in config/settings.py and read from there. LangSmith
itself wants two of them in the environment, so setup() mirrors those across and
says why. Nothing here reads os.environ.

Note that prompts carry repository source code to LangSmith, which is a hosted
service. That is the point of tracing, but it is worth knowing.
LANGSMITH_HIDE_INPUTS / LANGSMITH_HIDE_OUTPUTS keep the text local and send only
shapes and timings.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any

from langsmith import Client
from langsmith.run_helpers import traceable
from langsmith.run_trees import get_cached_client

from .logs import get_logger
from .settings import get_tracing_settings

if TYPE_CHECKING:
    from ..agents.models.base import Model

logger = get_logger("tracing")

# LangSmith and langchain-core decide whether to trace by reading these from the
# environment, and neither exposes a way to pass them in. That is the only reason
# this module still writes to os.environ: the values come from settings, but these
# two have to be mirrored back for the libraries to see them.
TRACING_FLAG = "LANGSMITH_TRACING_V2"
PROJECT_VAR = "LANGSMITH_PROJECT"

_client: Client | None = None


def is_enabled() -> bool:
    """Whether a LangSmith key is configured, which is what turns tracing on."""
    return get_tracing_settings().enabled


def setup() -> Client | None:
    """Build the one client that LangGraph and the model calls both use.

    get_cached_client both returns the client and caches it as langchain-core's
    default, which is what makes the whole trace one tree: LangGraph's tracer
    picks up the cached client, and the traceable calls below are handed the same
    object. Two clients would mean two trees, and hide_inputs set here would be
    ignored.

    Returns None when there is no key, so callers can tell "tracing off" from
    "tracing on" without asking twice. Safe to call more than once.
    """
    global _client

    settings = get_tracing_settings()

    if not settings.enabled:
        return None

    if _client is not None:
        return _client

    # Both are resolved through cached lookups inside the libraries, so they have
    # to be in place before the first trace. The project one matters for more than
    # tidiness: LangGraph reads it from the environment, so without this its spans
    # would land in a different project than the ones created below.
    os.environ[TRACING_FLAG] = "true"
    os.environ[PROJECT_VAR] = settings.langsmith_project

    _client = get_cached_client(
        api_key=settings.langsmith_api_key,
        api_url=settings.langsmith_endpoint,
        hide_inputs=settings.langsmith_hide_inputs,
        hide_outputs=settings.langsmith_hide_outputs,
    )

    logger.info(
        "tracing on: project=%r endpoint=%r",
        settings.langsmith_project, settings.langsmith_endpoint,
    )
    return _client


async def traced_agent_run[T](coro: Awaitable[T], *, name: str, **metadata: Any) -> T:
    """One agent execution as a single span.

    Wrapping the coroutine rather than the graph is what ties the trace together:
    LangGraph traces its own nodes as children of whichever span is open when it
    runs, so this span becomes the root and every node and model call hangs off
    it. The coroutine is awaited exactly once either way.
    """
    client = setup()

    if client is None:
        return await coro

    settings = get_tracing_settings()

    @traceable(
        name=name,
        run_type="chain",
        project_name=settings.langsmith_project,
        tags=settings.tag_list,
        metadata=metadata,
        client=client,
    )
    async def _run() -> T:
        return await coro

    return await _run()


async def traced_generate(model: Model, prompt: str) -> Any:
    """Call the model, recording the exchange when tracing is on.

    The metadata carries the size of the prompt rather than its text, so a trace
    is readable without paging through source code.
    """
    client = setup()

    if client is None:
        return await model.generate(prompt)

    settings = get_tracing_settings()

    @traceable(
        name=f"{model.settings.provider}/{model.settings.name}",
        run_type="llm",
        project_name=settings.langsmith_project,
        tags=settings.tag_list,
        metadata={"prompt_chars": len(prompt)},
        client=client,
    )
    async def _generate() -> Any:
        return await model.generate(prompt)

    return await _generate()