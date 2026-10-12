import { describe, it } from "node:test"
import assert from "node:assert/strict"
import Fastify from "fastify"
import { auditResponseSerialization } from "./responseSerializationAudit.js"

describe("response serialization audit", () => {
  it("detects fields silently removed by a response schema", async () => {
    const app = Fastify()
    auditResponseSerialization(app)
    app.get("/api/audit", { schema: { response: { 200: {
      type: "object", properties: { id: { type: "integer" } },
    } } } }, async () => ({ id: 1, name: "field missing from schema" }))
    const response = await app.inject({ method: "GET", url: "/api/audit" })
    assert.equal(response.statusCode, 200)
    assert.deepEqual(response.json(), { id: 1 })
    await assert.rejects(app.close(), /Response serialization changed controller payloads/)
  })

  it("accepts normal Date conversion, nulls and empty 204 responses", async () => {
    const app = Fastify()
    auditResponseSerialization(app)
    app.get("/api/audit", { schema: { response: { 200: {
      type: "object", properties: {
        at: { type: "string", format: "date-time" }, value: { type: ["string", "null"] },
      },
    } } } }, async () => ({ at: new Date("2026-10-11T00:00:00.000Z"), value: null }))
    app.delete("/api/audit", async (_request, reply) => reply.code(204).send())
    assert.equal((await app.inject({ method: "GET", url: "/api/audit" })).statusCode, 200)
    assert.equal((await app.inject({ method: "DELETE", url: "/api/audit" })).body, "")
    await app.close()
  })
})
