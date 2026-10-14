# Veraud

## Requirements
- [pnpm](https://github.com/pnpm/pnpm)
- [fnm](https://github.com/Schniz/fnm)
- [uv](https://github.com/astral-sh/uv)

#### Troubleshooting
- If you have any issues with fnm, follow the [shell setup guide](https://github.com/Schniz/fnm#shell-setup)

## Preparation
**Windows only**: Run `scripts/setup_dev_env.ps1` from the project root to install the required Node.js and Python versions and download all dependencies.

Once the setup is complete, you can start the services:
#### Frontend
```bash
cd frontend
pnpm run dev
```

#### Backend
```bash
cd backend
pnpm run dev
```

#### Agent server
```bash
cd agent-server
uv run dev
```

#### Agent benchmark
See [the workspace benchmark guide](docs/agent-server/benchmark.md) to evaluate
the analyzer, architect and judge on pinned repositories from `appdata/workspace`.

#### Repository analysis
See [the in-memory repository analysis guide](docs/agent-server/repository-analysis.md)
for deterministic structural analysis and source queries without model calls.

#### Repository agents
See [project orientation](docs/agent-server/project-orientation.md) and
[project architecture](docs/agent-server/project-architecture.md) for the focused
LangGraph agents, dedicated runners, evidence contracts, and offline protocol checks.
Their snapshot-bound execution primitives are described in
[the shared runtime guide](docs/agent-server/repository-runtime.md).
See [semantic validation](docs/agent-server/project-semantic-validation.md) for
independent claim review and the bounded architectural feedback cycle.
The [project architecture pipeline](docs/agent-server/project-architecture-pipeline.md)
exposes that composition for backend integration with typed results and stage hooks.
It also exposes [source-linked component diagrams](docs/agent-server/architecture-diagrams.md)
as structured data and deterministic Mermaid.
## Backend API documentation

With the backend running, open `http://<backend-host>:<backend-port>/docs` for
Swagger UI, or `/docs/json` for the OpenAPI specification. Use the backend port
configured for your environment, rather than the frontend port.

The portal documents all 27 backend HTTP operations and supports "Try it out".
See [the backend documentation index](docs/backend/README.md) for HTTP contracts,
architecture notes and WebSocket lifecycle documentation.

## Agent-server API documentation

With the agent-server running, open
`http://<agent-server-host>:<agent-server-port>/docs` for Swagger UI, `/redoc` for
ReDoc, or `/openapi.json` for its OpenAPI 3.1.0 specification. Use the agent-server
port configured for your environment.

The portal documents all four agent-server HTTP operations. See
[the agent-server documentation index](docs/agent-server/README.md) for agent
discovery, execution examples, configuration and backend callback flows.

### Documentation links in the frontend

The frontend header includes **Backend docs** and **Agent-server docs**, opening
each service's `/docs` portal in a new tab. Configure their service URLs in
`frontend/.env.local`, using `frontend/.env.example` as a reference:

```dotenv
VITE_BACKEND_URL=http://localhost:7501
VITE_AGENT_SERVER_URL=http://localhost:7502
```

These are also the default URLs when the variables are omitted.
`VITE_BACKEND_URL` is shared with the frontend's backend API requests. Restart
the frontend dev server after changing these variables, or rebuild for deployment.
