import { describe, it } from "node:test"
import assert from "node:assert/strict"
import Fastify from "fastify"
import { registerTaskRoutes } from "./task.controller.js"
import { TaskService } from "./task.service.js"
import { registerApiSchemas } from "../../infrastructure/openapi/registerApiSchemas.js"
import { auditResponseSerialization } from "../../tests/helpers/responseSerializationAudit.js"

describe("GET /api/tasks/active", () => {
  it("returns saved commands and null for tasks without a recorded command", async () => {
    const app = Fastify()
    auditResponseSerialization(app)
    registerApiSchemas(app)
    const task = { id: 1, projectId: 2, repositoryOwner: "acme", repositoryName: "repo", description: "cloning acme/repo", status: "Queued", kind: "clone", exitCode: null }
    const command = 'git clone --depth 1 git@github.com:acme/repo.git "/workspace/my repo"'
    const service = new TaskService(null as never, null as never)
    service.listActive = async () => [{ ...task, command }, { ...task, id: 3 }]
    registerTaskRoutes(app, service)
    try {
      const response = await app.inject({ method: "GET", url: "/api/tasks/active" })
      assert.equal(response.statusCode, 200)
      assert.deepEqual(response.json(), [{ ...task, command }, { ...task, id: 3, command: null }])
    } finally {
      await app.close()
    }
  })
})
