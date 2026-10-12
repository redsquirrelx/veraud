import type { FastifyInstance } from "fastify"
import swagger from "@fastify/swagger"
import swaggerUi from "@fastify/swagger-ui"

/** Register before application routes so Swagger can discover their schemas. */
export async function registerOpenApi(app: FastifyInstance): Promise<void> {
  await app.register(swagger, {
    openapi: {
      openapi: "3.0.3",
      info: {
        title: "Veraud Backend API",
        description: "HTTP API for projects, Git tasks, AI providers, and agent executions. See [WebSocket AsyncAPI documentation](/docs/ws) for realtime event contracts.",
        version: "1.0.0",
      },
      servers: [{ url: "/", description: "Current backend origin" }],
      tags: [
        { name: "Projects", description: "Register repositories, synchronize checkouts, preview files, and analyze project versions." },
        { name: "Project Git", description: "Inspect local branches, files and history, and change the checked-out version through Git tasks." },
        { name: "Tasks", description: "Queued and running Git tasks, including their recorded commands." },
        { name: "AI Providers", description: "Read provider configuration and manage provider-scoped models and masked credentials." },
        { name: "Agent Executions", description: "Start agents, inspect executions and report lifecycle transitions through callbacks." },
        { name: "Status", description: "Backend health and agent-server reachability." },
      ],
    },
  })

  await app.register(swaggerUi, {
    routePrefix: "/docs",
    uiConfig: {
      docExpansion: "none",
      deepLinking: true,
      filter: true,
      displayRequestDuration: true,
      operationsSorter: "alpha",
    },
  })
}
