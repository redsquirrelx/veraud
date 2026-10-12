import { describe, it } from "node:test"
import assert from "node:assert/strict"
import Fastify from "fastify"
import { API_SCHEMAS, registerApiSchemas } from "./registerApiSchemas.js"
import { registerOpenApi } from "./registerOpenApi.js"

const execution = {
  id: 1, evaluationId: null, agentType: "analyzer", status: "Waiting",
  result: null, error: null, inputTokens: null, outputTokens: null,
  createdAt: "2026-10-11T00:00:00.000Z", startedAt: null, finishedAt: null,
}

describe("shared API schemas", () => {
  it("resolves every schema and converts nullable fields and references to OpenAPI 3.0", async () => {
    const app = Fastify()
    await registerOpenApi(app)
    registerApiSchemas(app)
    for (const schema of API_SCHEMAS) {
      app.post(`/schema/${schema.$id}`, { schema: { body: { $ref: `${schema.$id}#` }, response: { 200: { $ref: `${schema.$id}#` } } } }, async (request) => request.body)
    }
    try {
      await app.ready()
      assert.equal(Object.keys(app.getSchemas()).length, API_SCHEMAS.length)
      const response = await app.inject({ method: "GET", url: "/docs/json" })
      assert.equal(response.statusCode, 200)
      const specification = response.json()
      const schemas = Object.values(specification.components.schemas) as Array<{ properties?: Record<string, { nullable?: boolean; type?: unknown }> }>
      const agent = schemas.find((schema) => schema.properties?.agentType && schema.properties?.finishedAt)
      assert.equal(agent?.properties?.finishedAt?.nullable, true)
      assert.equal(agent?.properties?.finishedAt?.type, "string")
      // OpenAPI 3.0 forbids JSON Schema's null type and type arrays.
      function verify(value: unknown): void {
        if (value === null || typeof value !== "object") return
        for (const [key, child] of Object.entries(value)) {
          if (key === "type") {
            assert.notEqual(child, "null")
            assert.equal(Array.isArray(child), false)
          }
          if (key === "$ref") {
            assert.equal(typeof child, "string")
            const component = String(child).replace("#/components/schemas/", "")
            assert.ok(specification.components.schemas[component], `Unresolved reference: ${child}`)
          }
          verify(child)
        }
      }
      verify(specification.components.schemas)

      for (const nestedExecution of [null, execution]) {
        const version = { id: 2, branch: null, commitHash: null, analysisStatus: "Pending", analyzedAt: null, evaluationId: null, execution: nestedExecution, derivedStatus: nestedExecution ? "Waiting" : "NeverAnalyzed" }
        const result = await app.inject({ method: "POST", url: "/schema/VersionAnalysis", payload: version })
        assert.equal(result.statusCode, 200, result.body)
        assert.deepEqual(result.json(), version)
      }
      const missingRequired = { ...execution } as Record<string, unknown>
      delete missingRequired.finishedAt
      const invalid = await app.inject({ method: "POST", url: "/schema/AgentExecution", payload: missingRequired })
      assert.equal(invalid.statusCode, 400, "Nullable fields are still required")
    } finally {
      await app.close()
    }
  })

  it("serializes nested public provider responses without exposing stored API keys", async () => {
    const app = Fastify()
    registerApiSchemas(app)
    const provider = { id: 1, name: "OpenAI", models: [{ id: 2, name: "model", inUse: true }], credentials: [{ id: 3, name: "prod", apiKeyPreview: "****1234", inUse: false }] }
    app.get("/provider", { schema: { response: { 200: { $ref: "AiProvider#" } } } }, async () => ({ ...provider, credentials: provider.credentials.map((credential) => ({ ...credential, apiKey: "secret-1234" })) }))
    try {
      const response = await app.inject({ method: "GET", url: "/provider" })
      assert.equal(response.statusCode, 200)
      assert.deepEqual(response.json(), provider)
      assert.ok(!response.body.includes("secret-1234"))
    } finally {
      await app.close()
    }
  })

  it("preserves Date serialization, nullable task fields and the existing success spelling", async () => {
    const app = Fastify()
    registerApiSchemas(app)
    app.get("/project", { schema: { response: { 200: { $ref: "ProjectSummary#" } } } }, async () => ({ id: 1, repositoryOwner: "acme", repositoryName: "repo", cloneProtocol: "ssh", status: "READY", registeredAt: new Date(execution.createdAt), lastSyncedAt: null, branch: null, commitHash: null }))
    const task = { id: 2, projectId: 1, repositoryOwner: "acme", repositoryName: "repo", description: null, command: null, status: "Succeded", kind: "unknown", exitCode: 0 }
    app.get("/task", { schema: { response: { 200: { $ref: "Task#" } } } }, async () => task)
    try {
      const project = await app.inject({ method: "GET", url: "/project" })
      assert.equal(project.statusCode, 200)
      assert.equal(project.json().registeredAt, execution.createdAt)
      assert.equal(project.json().lastSyncedAt, null)
      const response = await app.inject({ method: "GET", url: "/task" })
      assert.equal(response.statusCode, 200)
      assert.deepEqual(response.json(), task)
    } finally {
      await app.close()
    }
  })
})
