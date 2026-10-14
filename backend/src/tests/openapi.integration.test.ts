import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import SwaggerParser from "@apidevtools/swagger-parser"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { BACKEND_AGENT_TYPES } from "../modules/agent-settings/agent-types.js"

describe("OpenAPI portal", () => {
  it("serves Swagger UI, its assets, and the discovered backend specification", async () => {
    const directory = mkdtempSync(join(tmpdir(), "veraud-openapi-"))
    const databaseUrl = `file:${join(directory, "test.db")}`
    const backendRoot = fileURLToPath(new URL("../../", import.meta.url))
    execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], {
      cwd: backendRoot,
      env: { ...process.env, DATABASE_URL: databaseUrl },
      stdio: "ignore",
    })
    const { app, db } = await buildApp({ databaseUrl, workspaceDir: join(directory, "workspace"), silent: true })
    try {
      const portal = await app.inject({ method: "GET", url: "/docs/" })
      assert.equal(portal.statusCode, 200)
      assert.match(String(portal.headers["content-type"]), /text\/html/)
      assert.match(portal.body, /swagger-ui/)

      const asset = await app.inject({ method: "GET", url: "/docs/static/swagger-ui.css" })
      assert.equal(asset.statusCode, 200)
      assert.match(String(asset.headers["content-type"]), /text\/css/)

      const response = await app.inject({ method: "GET", url: "/docs/json" })
      assert.equal(response.statusCode, 200)
      const specification = response.json()
      await SwaggerParser.validate(structuredClone(specification))
      assert.equal(specification.openapi, "3.0.3")
      assert.equal(specification.info.title, "Veraud Backend API")
      assert.equal(specification.info.version, "1.0.0")
      assert.deepEqual(specification.servers, [{ url: "/", description: "Current backend origin" }])
      assert.deepEqual(specification.tags.map((tag: { name: string }) => tag.name), ["Projects", "Project Git", "Tasks", "AI Providers", "Agent Executions", "Agent Settings", "Status"])
      assert.ok(specification.paths["/api/projects"]?.post, "Swagger must be registered before controllers")
      assert.ok(specification.paths["/api/tasks/active"]?.get)
      assert.ok(specification.paths["/api/ai-providers"]?.get)
      assert.ok(specification.paths["/api/agent-executions"]?.post)
      assert.ok(specification.paths["/status"]?.get)
      assert.ok(!specification.paths["/docs/json"], "Swagger must not document its own routes")
      assert.ok(!specification.paths["/ws"], "WebSocket contracts are documented separately")
      const operations = Object.values(specification.paths).flatMap((item: unknown) =>
        Object.entries(item as Record<string, unknown>).filter(([method]) => ["get", "post", "patch", "delete", "put"].includes(method)).map(([, operation]) => operation as { tags?: string[]; summary?: string; description?: string; responses?: Record<string, unknown> }),
      )
      assert.equal(operations.length, 31)
      const expectedOperations = [
        "DELETE /api/ai-providers/{id}/credentials/{nestedId}",
        "DELETE /api/ai-providers/{id}/models/{nestedId}",
        "GET /api/agent-executions/{id}",
        "GET /api/agent-settings",
        "GET /api/ai-providers",
        "GET /api/ai-providers/{id}",
        "GET /api/projects",
        "GET /api/projects/{id}/versions",
        "GET /api/tasks/active",
        "GET /status",
        "PATCH /api/ai-providers/{id}/credentials/{nestedId}",
        "PATCH /api/ai-providers/{id}/models/{nestedId}",
        "POST /api/agent-executions",
        "POST /api/agent-executions/direct",
        "POST /api/agent-executions/{id}/completion",
        "POST /api/agent-executions/{id}/progress",
        "POST /api/agent-executions/{id}/running",
        "POST /api/agent-settings/{agentType}/verify",
        "POST /api/ai-providers/{id}/credentials",
        "POST /api/ai-providers/{id}/models",
        "POST /api/projects",
        "POST /api/projects/{id}/architecture",
        "POST /api/projects/{id}/file",
        "POST /api/projects/{id}/git/branches",
        "POST /api/projects/{id}/git/checkout",
        "POST /api/projects/{id}/git/checkout-branch",
        "POST /api/projects/{id}/git/log",
        "POST /api/projects/{id}/git/rev-parse",
        "POST /api/projects/{id}/git/tree",
        "POST /api/projects/{id}/sync",
        "PUT /api/agent-settings/{agentType}",
      ].sort()
      const documentedOperations = Object.entries(specification.paths).flatMap(([path, item]) =>
        Object.keys(item as Record<string, unknown>).filter((method) => ["get", "post", "patch", "delete", "put"].includes(method)).map((method) => `${method.toUpperCase()} ${path}`),
      ).sort()
      assert.deepEqual(documentedOperations, expectedOperations, "OpenAPI must cover the expected HTTP methods and paths")
      for (const operation of operations) {
        assert.ok(operation.tags?.length)
        assert.ok(operation.summary)
        assert.ok(operation.description)
        assert.ok(Object.keys(operation.responses ?? {}).some((code) => /^2\d\d$/.test(code)))
      }
      for (const route of ["/api/ai-providers/{id}/models/{nestedId}", "/api/ai-providers/{id}/credentials/{nestedId}"]) {
        assert.ok(!specification.paths[route].delete.responses["204"].content, "204 must not advertise a response body")
      }
      const invalidBody = await app.inject({ method: "POST", url: "/api/projects", payload: {} })
      assert.equal(invalidBody.statusCode, 400)
      assert.equal(invalidBody.json().code, "FST_ERR_VALIDATION")
      assert.equal(invalidBody.json().statusCode, 400)
      assert.equal(invalidBody.json().error, "Bad Request")
      assert.ok(invalidBody.json().message)
      const missingProvider = await app.inject({ method: "GET", url: "/api/ai-providers/0" })
      assert.equal(missingProvider.statusCode, 404)
      assert.deepEqual(missingProvider.json(), { message: "AI provider 0 does not exist" })
      const missingExecution = await app.inject({ method: "GET", url: "/api/agent-executions/0" })
      assert.equal(missingExecution.statusCode, 404)
      assert.deepEqual(missingExecution.json(), { error: "Agent execution 0 not found" })
      const agentSettings = await app.inject({ method: "GET", url: "/api/agent-settings" })
      assert.equal(agentSettings.statusCode, 200)
      assert.deepEqual(agentSettings.json(), [...BACKEND_AGENT_TYPES].sort().map((agentType) => ({
        agentType, configured: false, configuration: null, verification: { status: "not_verified", checkedAt: null, message: null },
      })))
      const architectureResponse = specification.paths["/api/projects/{id}/architecture"].post.responses["201"].content["application/json"].schema
      assert.ok(architectureResponse.properties.executions.properties.orientation)
      assert.ok(architectureResponse.properties.executions.properties.architecture)
      assert.ok(architectureResponse.properties.executions.properties.semantic_validation)
      const dereferenced = await SwaggerParser.dereference(structuredClone(specification)) as typeof specification
      assert.ok(dereferenced.paths["/api/projects/{id}/versions"].get.responses["200"].content["application/json"].schema.items.properties.executions)
    } finally {
      await app.close()
      await db.$disconnect()
      rmSync(directory, { recursive: true, force: true })
    }
  })
})
