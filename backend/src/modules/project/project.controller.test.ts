import { describe, it } from "node:test"
import assert from "node:assert/strict"
import Fastify from "fastify"
import { registerProjectRoutes } from "./project.controller.js"
import { ProjectService } from "./project.service.js"

describe("POST /api/projects clone preference", () => {
  it("accepts both modes, defaults omitted values to full, and rejects invalid values", async () => {
    const calls: Array<{ url: string; shallowClone: boolean }> = []
    const service = new ProjectService(null as never, null as never, null as never, "", null as never)
    service.registerProject = async (url, shallowClone = false) => {
      calls.push({ url, shallowClone })
      return { id: 1, repositoryOwner: "acme", repositoryName: "repo", status: "QUEUED" }
    }
    const app = Fastify()
    registerProjectRoutes(app, service)
    try {
      for (const shallowClone of [false, true, undefined]) {
        const response = await app.inject({ method: "POST", url: "/api/projects", payload: { repositoryUrl: "git@github.com:acme/repo.git", ...(shallowClone === undefined ? {} : { shallowClone }) } })
        assert.equal(response.statusCode, 201)
        assert.deepEqual(calls.at(-1), { url: "git@github.com:acme/repo.git", shallowClone: shallowClone ?? false })
      }
      const response = await app.inject({ method: "POST", url: "/api/projects", payload: { repositoryUrl: "git@github.com:acme/repo.git", shallowClone: "invalid" } })
      assert.equal(response.statusCode, 400)
      assert.equal(calls.length, 3)
    } finally {
      await app.close()
    }
  })
})
