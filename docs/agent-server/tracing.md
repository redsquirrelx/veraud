# LangSmith Tracing

Traces every agent run: the graph, each node inside it, and each model call.
Source of truth: `agent-server/src/server/config/tracing.py`

## Turning it on

One variable. Nothing else is required:

```bash
LANGSMITH_API_KEY=lsv2_pt_...
```

Put it in the repo `.env` at the root or export it before starting the server.
The module loads that file itself, resolved from its own location rather than
the working directory, so it does not matter where the process was started from.

Without a key, `tracing.setup()` returns `None`, touches no environment
variables, and the two helpers become plain pass-throughs: agents behave exactly
as before and pay nothing.

| Variable | Default | Effect |
|---|---|---|
| `LANGSMITH_API_KEY` | — | The switch. Absent means no tracing. |
| `LANGSMITH_PROJECT` | `agent-server` | Project the traces land in. |
| `LANGSMITH_TAGS` | — | Comma separated tags added to every span. |
| `LANGSMITH_ENDPOINT` | LangSmith cloud | Read by LangSmith; point at a self-hosted deployment. |
| `LANGSMITH_HIDE_INPUTS` | `false` | Send prompt sizes instead of prompt text. |
| `LANGSMITH_HIDE_OUTPUTS` | `false` | Send response sizes instead of response text. |

Values already exported in the environment win over the file.

### Why the .env is loaded here

Pydantic's `Settings` reads the file into its own fields and leaves the
environment alone, so anything reading `os.environ` sees nothing. LangSmith
reads `LANGSMITH_ENDPOINT` and `LANGSMITH_TRACING` that same way, which is why
`config/tracing.py` calls `load_dotenv` instead of only parsing the file for the
two values it needs.

It does not reuse `Settings` on purpose: that class has required fields, so
importing it fails without a `.env`, and the dev runners are meant to work
without one.

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
| `app/execution_service.py` | `setup()` at construction; `traced_agent_run` around the timed run |
| `agents/analyzer/agent.py` | `traced_generate` instead of `model.generate` |
| `agents/dummy/agent.py` | same |
| `config/tracing.py` | the module itself |

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