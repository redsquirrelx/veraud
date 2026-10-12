# Agent-server documentation

## HTTP API reference

Start the agent-server and open its own host and port:

```text
http://<agent-server-host>:<agent-server-port>/docs
http://<agent-server-host>:<agent-server-port>/redoc
http://<agent-server-host>:<agent-server-port>/openapi.json
```

Swagger UI is the central HTTP reference. It documents four operations grouped
under Status and Agents. The generated specification uses OpenAPI 3.1.0.
Use the agent-server port rather than the backend or frontend port. Requests
use the origin serving the portal; no development host/port is hardcoded.

- [Agent discovery, execution, configuration and callbacks](execution-guide.md).
- [OpenAPI setup, verification and maintenance](openapi.md).
- [Initial HTTP endpoint inventory](http-endpoint-inventory.md).

Route metadata and Pydantic models are the source of truth for HTTP contracts.
Markdown explains usage and architecture. The backend has its own
[documentation portal](../backend/README.md); combining the two specifications
in a service selector is a future integration.
