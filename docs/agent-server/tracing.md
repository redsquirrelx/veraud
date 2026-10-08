# LangSmith Tracing

Traces every agent run: the graph, each node inside it, and each model call.
Source of truth: `agent-server/src/server/config/tracing.py`

## Turning it on

One variable. Nothing else is required:

```bash
LANGSMITH_API_KEY=lsv2_pt_...
```

Put it in the repo `.env` at the root or export it before starting the server.

Without a key, `tracing.setup()` returns `None`, writes nothing to the
environment, and the two helpers become plain pass-throughs: agents behave
exactly as before and pay nothing.

| Variable | Field | Default | Effect |
|---|---|---|---|
| `LANGSMITH_API_KEY` | `langsmith_api_key` | — | The switch. Absent means no tracing. |
| `LANGSMITH_PROJECT` | `langsmith_project` | `agent-server` | Project the traces land in. |
| `LANGSMITH_TAGS` | `langsmith_tags` | — | Comma separated tags added to every span. |
| `LANGSMITH_ENDPOINT` | `langsmith_endpoint` | LangSmith cloud | Point at a self-hosted deployment. |
| `LANGSMITH_HIDE_INPUTS` | `langsmith_hide_inputs` | `false` | Send prompt sizes instead of prompt text. |
| `LANGSMITH_HIDE_OUTPUTS` | `langsmith_hide_outputs` | `false` | Send response sizes instead of response text. |

### Where the variables live

Every variable the server reads is declared in `config/settings.py`, and
`config/tracing.py` reads it from there. Two classes, split because they fail
differently:

- `ServerSettings` — required. A missing value is a deployment mistake, so
  `get_server_settings()` raises `ValidationError`.
- `TracingSettings` — a default for everything, so tracing being unconfigured
  never breaks an import. `get_tracing_settings()` always succeeds.

Both read the repo `.env`, whose path is resolved from `settings.py` rather than
from the working directory, so the runners work from anywhere.

### Why tracing still touches os.environ

Pydantic reads the file into its own fields and leaves the environment alone, so
a declared variable is not visible to code reading `os.environ`. LangSmith and
langchain-core both resolve their tracing flag and the project name that way, and
neither exposes a way to pass them in, so `tracing.setup()` mirrors exactly those
two back:

```python
os.environ["LANGSMITH_TRACING_V2"] = "true"
os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
```

The project one is not cosmetic. LangGraph resolves its spans' project from the
environment, while the `traceable` spans take it as an argument. Without the
mirror, the two halves of the same trace would land in different projects.

## The shape of a trace

```
analyzer                    one span per agent execution
  LangGraph                 the graph, traced by langchain-core
    hypothesize             one span per node
      gemini/flash          one span per model call, under the node that made it
    select
    read                    no child: this node only touches the filesystem
    verify                  also shows the conditional edge, _after_verify
    synthesize
      gemini/flash
```

The analyzer loop shows up directly: if it needed a second read round, there are
two `select`/`read`/`verify` spans in sequence. When a model call fails, the span
records the error instead of the response.

Root spans carry `model` and `timeout_seconds`. Model spans carry
`prompt_chars`.

## How it stays one tree

Two things have to agree, and neither is automatic:

- **One `Client`.** `setup()` builds it with `get_cached_client(...)`, which also
  makes it langchain-core's default. LangGraph's tracer picks up the cached one,
  and every `traceable` below is handed the same object explicitly. Two clients
  would produce two disconnected trees and silently ignore `hide_inputs`.
- **The tracing flag.** `langsmith` 0.14 resolves tracing through cached
  lookups, so `setup()` sets `LANGSMITH_TRACING_V2=true` and
  `LANGSMITH_PROJECT` before the first trace. Setting them later has no effect.
  `setup()` runs in `AgentExecutionService.__init__`, which is before any agent
  builds a graph.

Nesting works because `langsmith.tracing_is_enabled()` returns true whenever a
span is already open, which is what makes langchain-core trace the graph as a
child of the surrounding span.

## Where it is wired

| File | What it does |
|---|---|
| `config/settings.py` | declares every variable the server reads |
| `config/tracing.py` | the module itself |
| `app/execution_service.py` | `setup()` at construction; `traced_agent_run` around the timed run |
| `agents/analyzer/agent.py` | `traced_generate` instead of `model.generate` |
| `agents/dummy/agent.py` | same |

`traced_agent_run` wraps the coroutine rather than the graph on purpose: that is
what makes the agent span the root that the graph hangs off. The coroutine is
awaited exactly once either way.

## Source code leaves the machine

Prompts carry repository source code, and tracing sends prompts to LangSmith,
which is a hosted service. That is the point of tracing, and hiding inputs makes
the traces much less useful, so it is a deliberate default rather than an
oversight.

`LANGSMITH_HIDE_INPUTS=true` / `LANGSMITH_HIDE_OUTPUTS=true` keep the text local
and send only shapes and timings, which is enough to debug latency and token
spend without shipping anyone's code.

## Not wired yet

The backend creates an `agent_execution` row and agents call back to report
progress, but nothing passes the row id to the agent, so a trace cannot be
linked to the execution shown in the UI. Tagging traces with that id is the
obvious next step once the execution id reaches the agent
(see `docs/backend/agent-execution.md`).